"""Tests for /api/v1/auth and the authentication dependencies."""

from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.security import create_access_token
from models import Role, User
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
            {"role": "admin", "business_id": 1},  # no sub
            {"sub": "1", "business_id": 1},  # no role
            {"sub": "abc", "role": "admin", "business_id": 1},  # sub not numeric
            {"sub": "1", "role": "superuser", "business_id": 1},  # unknown role
        ],
        ids=["no-sub", "no-role", "sub-not-int", "unknown-role"],
    )
    def test_malformed_claims(self, client: TestClient, payload: dict) -> None:
        from core.config import settings

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
