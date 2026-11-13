"""Tests for /api/v1/auth and the authentication dependencies."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.security import create_access_token
from models import Business, BusinessStatus, Role, User
from tests.conftest import DEFAULT_PASSWORD, LOGIN_URL, login

ME_URL = "/api/v1/auth/me"
LOGOUT_URL = "/api/v1/auth/logout"


OTHER_KEY = "another-key-that-is-at-least-32-bytes-long"


class TestLogin:
    def test_login_returns_token(self, client: TestClient, two_businesses) -> None:
        response = client.post(
            LOGIN_URL, data={"username": "admin.a@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"].count(".") == 2

    def test_token_claims_match_user(self, client: TestClient, two_businesses) -> None:
        token = login(client, "admin.a@demo.mx")
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload["sub"] == str(two_businesses["admin_a"].id)
        assert payload["role"] == "admin"
        assert payload["business_id"] == two_businesses["business_a"].id

    def test_login_sets_secure_session_cookie(self, client: TestClient, two_businesses) -> None:
        response = client.post(
            LOGIN_URL, data={"username": "admin.a@demo.mx", "password": DEFAULT_PASSWORD}
        )
        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith("access_token=")
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "max-age=28800" in cookie  # 480 minutes
        assert "path=/" in cookie

    def test_cookie_value_equals_body_token(self, client: TestClient, two_businesses) -> None:
        token = login(client, "admin.a@demo.mx")
        assert client.cookies.get("access_token") == token

    def test_email_is_case_insensitive(self, client: TestClient, two_businesses) -> None:
        response = client.post(
            LOGIN_URL, data={"username": "ADMIN.A@Demo.MX", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 200

    def test_wrong_password(self, client: TestClient, two_businesses) -> None:
        response = client.post(LOGIN_URL, data={"username": "admin.a@demo.mx", "password": "bad"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password"
        assert "set-cookie" not in response.headers

    def test_unknown_email_gives_same_error_as_wrong_password(
        self, client: TestClient, two_businesses
    ) -> None:
        # Same message: the API does not reveal which emails exist.
        response = client.post(LOGIN_URL, data={"username": "nobody@demo.mx", "password": "x"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password"

    def test_inactive_user_cannot_login(self, client: TestClient, make_business, make_user) -> None:
        make_user("off@demo.mx", business=make_business(), is_active=False)
        response = client.post(
            LOGIN_URL, data={"username": "off@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Inactive user"

    def test_platform_user_can_login(self, client: TestClient, two_businesses) -> None:
        token = login(client, "owner@memberplus.mx")
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload["role"] == "platform"
        assert payload["business_id"] is None

    @pytest.mark.parametrize(
        "data",
        [{}, {"username": "admin.a@demo.mx"}, {"password": DEFAULT_PASSWORD}],
        ids=["empty", "no-password", "no-username"],
    )
    def test_missing_fields(self, client: TestClient, data: dict) -> None:
        assert client.post(LOGIN_URL, data=data).status_code == 422

    def test_json_body_is_not_accepted(self, client: TestClient, two_businesses) -> None:
        # OAuth2 password flow requires form data.
        response = client.post(
            LOGIN_URL, json={"username": "admin.a@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 422


class TestCurrentUserBusiness:
    """`/auth/me` carries the business so the frontend header shows its name."""

    def test_admin_gets_their_business(self, client: TestClient, two_businesses) -> None:
        business_a = two_businesses["business_a"]
        login(client, "admin.a@demo.mx")
        body = client.get(ME_URL).json()
        assert body["business"] == {
            "id": business_a.id,
            "name": "Business A",
            "logo_url": None,
            "status": "active",
        }

    def test_employee_gets_their_business(self, client: TestClient, two_businesses) -> None:
        login(client, "employee.a@demo.mx")
        business = client.get(ME_URL).json()["business"]
        assert business["id"] == two_businesses["business_a"].id
        assert business["name"] == "Business A"

    def test_business_matches_business_id(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.b@demo.mx")
        body = client.get(ME_URL).json()
        assert body["business"]["id"] == body["business_id"] == two_businesses["business_b"].id
        assert body["business"]["name"] == "Business B"

    def test_platform_owner_has_no_business(self, client: TestClient, two_businesses) -> None:
        login(client, "owner@memberplus.mx")
        body = client.get(ME_URL).json()
        assert body["business_id"] is None
        assert body["business"] is None

    def test_status_and_logo_come_from_the_database(
        self, client: TestClient, session: Session, make_business, make_user
    ) -> None:
        business = make_business("Café Aurora", status=BusinessStatus.TRIAL)
        business.logo_url = "https://cdn.example.mx/aurora.png"
        session.add(business)
        session.commit()
        make_user("caja@cafe-aurora.mx", business=business, role=Role.EMPLOYEE)

        login(client, "caja@cafe-aurora.mx")
        body = client.get(ME_URL).json()["business"]
        assert body["name"] == "Café Aurora"
        assert body["status"] == "trial"
        assert body["logo_url"] == "https://cdn.example.mx/aurora.png"

    def test_business_exposes_only_header_fields(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        business = client.get(ME_URL).json()["business"]
        assert set(business) == {"id", "name", "logo_url", "status"}


class TestCurrentUser:
    def test_me_with_cookie(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(ME_URL).json()
        assert body["email"] == "admin.a@demo.mx"
        assert body["role"] == "admin"
        assert body["business_id"] == two_businesses["business_a"].id

    def test_me_with_bearer_header(self, client: TestClient, two_businesses) -> None:
        token = login(client, "employee.a@demo.mx")
        client.cookies.clear()
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["role"] == "employee"

    def test_me_never_exposes_password_hash(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        body = client.get(ME_URL).json()
        assert "hashed_password" not in body
        assert "password" not in body
        assert set(body) == {
            "id",
            "business_id",
            "name",
            "email",
            "role",
            "is_active",
            "created_at",
            "business",
        }

    def test_cookie_has_priority_over_bearer(self, client: TestClient, two_businesses) -> None:
        token_b = login(client, "admin.b@demo.mx")
        client.cookies.clear()
        login(client, "admin.a@demo.mx")  # cookie = admin A
        body = client.get(ME_URL, headers={"Authorization": f"Bearer {token_b}"}).json()
        assert body["email"] == "admin.a@demo.mx"

    def test_without_token(self, client: TestClient) -> None:
        response = client.get(ME_URL)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_garbage_token(self, client: TestClient) -> None:
        response = client.get(ME_URL, headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401

    def test_expired_token(self, client: TestClient, two_businesses) -> None:
        token = create_access_token(
            user_id=two_businesses["admin_a"].id,
            role="admin",
            business_id=two_businesses["business_a"].id,
            expires_delta=timedelta(seconds=-1),
        )
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_signed_with_another_key(self, client: TestClient, two_businesses) -> None:
        token = jwt.encode(
            {"sub": str(two_businesses["admin_a"].id), "role": "admin", "business_id": 1},
            OTHER_KEY,
            algorithm="HS256",
        )
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "payload",
        [
            {"role": "admin", "business_id": 1, "jti": "a"},  # no sub
            {"sub": "1", "business_id": 1, "jti": "a"},  # no role
            {"sub": "abc", "role": "admin", "business_id": 1, "jti": "a"},  # sub not numeric
            {"sub": "1", "role": "superuser", "business_id": 1, "jti": "a"},  # unknown role
            {"sub": "1", "role": "admin", "business_id": 1},  # no jti (tokens before H2)
        ],
        ids=["no-sub", "no-role", "sub-not-int", "unknown-role", "no-jti"],
    )
    def test_malformed_claims(self, client: TestClient, two_businesses, payload: dict) -> None:
        from core.config import settings

        payload = {**payload, "exp": datetime.now(UTC) + timedelta(minutes=5)}
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_of_deleted_user(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        token = login(client, "employee.a@demo.mx")
        client.cookies.clear()
        session.delete(session.get(User, two_businesses["employee_a"].id))
        session.commit()
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_user_deactivated_after_login(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        login(client, "employee.a@demo.mx")
        user = session.get(User, two_businesses["employee_a"].id)
        user.is_active = False
        session.add(user)
        session.commit()
        response = client.get(ME_URL)
        assert response.status_code == 403
        assert response.json()["detail"] == "Inactive user"

    def test_role_comes_from_database_not_from_token(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        # The token still says "employee", but the DB was changed to admin.
        login(client, "employee.a@demo.mx")
        user = session.get(User, two_businesses["employee_a"].id)
        user.role = Role.ADMIN
        session.add(user)
        session.commit()
        assert client.get(ME_URL).json()["role"] == "admin"
        assert client.get("/api/v1/user/list").status_code == 200


class TestBusinessStatus:
    """H1: a suspended business loses access, both at login and mid-session."""

    def test_suspended_business_cannot_login(
        self, client: TestClient, make_business, make_user
    ) -> None:
        business = make_business("Suspended", status=BusinessStatus.SUSPENDED)
        make_user("suspended@demo.mx", business=business)
        response = client.post(
            LOGIN_URL, data={"username": "suspended@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Business suspended"
        assert "set-cookie" not in response.headers

    def test_suspended_business_message_needs_valid_password(
        self, client: TestClient, make_business, make_user
    ) -> None:
        # Wrong password still gives 401: the status is not revealed to strangers.
        business = make_business("Suspended", status=BusinessStatus.SUSPENDED)
        make_user("suspended@demo.mx", business=business)
        response = client.post(LOGIN_URL, data={"username": "suspended@demo.mx", "password": "x"})
        assert response.status_code == 401

    @pytest.mark.parametrize("status", [BusinessStatus.TRIAL, BusinessStatus.ACTIVE])
    def test_trial_and_active_businesses_can_login(
        self, client: TestClient, make_business, make_user, status: BusinessStatus
    ) -> None:
        make_user("ok@demo.mx", business=make_business("Shop", status=status))
        login(client, "ok@demo.mx")

    def test_open_session_is_cut_when_business_is_suspended(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        login(client, "employee.a@demo.mx")
        assert client.get(ME_URL).status_code == 200

        business = session.get(Business, two_businesses["business_a"].id)
        business.status = BusinessStatus.SUSPENDED
        session.add(business)
        session.commit()

        response = client.get(ME_URL)
        assert response.status_code == 403
        assert response.json()["detail"] == "Business suspended"

    def test_suspending_a_does_not_affect_b(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = session.get(Business, two_businesses["business_a"].id)
        business.status = BusinessStatus.SUSPENDED
        session.add(business)
        session.commit()
        login(client, "admin.b@demo.mx")
        assert client.get("/api/v1/user/list").status_code == 200

    def test_platform_owner_is_not_affected(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        for key in ("business_a", "business_b"):
            business = session.get(Business, two_businesses[key].id)
            business.status = BusinessStatus.SUSPENDED
            session.add(business)
        session.commit()
        login(client, "owner@memberplus.mx")
        assert client.get(ME_URL).status_code == 200


class TestLogout:
    def test_logout_clears_cookie(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(LOGOUT_URL)
        assert response.status_code == 204
        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith('access_token=""') or cookie.startswith("access_token=;")
        assert "max-age=0" in cookie
        assert client.get(ME_URL).status_code == 401

    def test_logout_without_session(self, client: TestClient) -> None:
        assert client.post(LOGOUT_URL).status_code == 204

    def test_token_copy_is_invalid_after_logout(self, client: TestClient, two_businesses) -> None:
        # H2: deleting the cookie is not enough; the token itself is revoked.
        token = login(client, "admin.a@demo.mx")
        client.post(LOGOUT_URL)
        client.cookies.clear()
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_logout_with_bearer_revokes_it(self, client: TestClient, two_businesses) -> None:
        # The cashier reader and Swagger log out with the header, not the cookie.
        token = login(client, "employee.a@demo.mx")
        client.cookies.clear()
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post(LOGOUT_URL, headers=headers).status_code == 204
        assert client.get(ME_URL, headers=headers).status_code == 401

    def test_other_sessions_stay_open(self, client: TestClient, two_businesses) -> None:
        # Logging out on one device does not close the user's other sessions.
        laptop = login(client, "admin.a@demo.mx")
        client.cookies.clear()
        phone = login(client, "admin.a@demo.mx")
        client.cookies.clear()
        assert laptop != phone
        client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {laptop}"})
        assert client.get(ME_URL, headers={"Authorization": f"Bearer {laptop}"}).status_code == 401
        assert client.get(ME_URL, headers={"Authorization": f"Bearer {phone}"}).status_code == 200

    def test_logout_twice_is_harmless(self, client: TestClient, two_businesses) -> None:
        token = login(client, "admin.a@demo.mx")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post(LOGOUT_URL, headers=headers).status_code == 204
        assert client.post(LOGOUT_URL, headers=headers).status_code == 204

    @pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c"], ids=["garbage", "bad-parts"])
    def test_logout_with_invalid_token(self, client: TestClient, token: str) -> None:
        response = client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 204

    def test_logout_with_expired_token(self, client: TestClient, two_businesses) -> None:
        token = create_access_token(
            user_id=two_businesses["admin_a"].id,
            role="admin",
            business_id=two_businesses["business_a"].id,
            expires_delta=timedelta(seconds=-1),
        )
        response = client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 204

    def test_logging_in_again_after_logout_works(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        client.post(LOGOUT_URL)
        login(client, "admin.a@demo.mx")
        assert client.get(ME_URL).status_code == 200
