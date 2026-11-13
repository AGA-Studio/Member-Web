"""Stable `code` in business errors (API contract, section 1.2; DECISIÓN 7).

The frontend chooses the message from `code`, so each code is pinned here.
`detail` keeps its wording; other tests already check it.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import BusinessStatus, Role
from tests.conftest import DEFAULT_PASSWORD, LOGIN_URL, login

ME_URL = "/api/v1/auth/me"
USER_CREATE_URL = "/api/v1/user/create"


def post_login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD):
    return client.post(LOGIN_URL, data={"username": email, "password": password})


class TestLoginCodes:
    def test_wrong_password_is_invalid_credentials(
        self, client: TestClient, two_businesses
    ) -> None:
        response = post_login(client, "admin.a@demo.mx", "wrong-password")
        assert response.status_code == 401
        assert response.json() == {
            "detail": "Incorrect email or password",
            "code": "invalid_credentials",
        }
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_unknown_email_is_invalid_credentials(self, client: TestClient) -> None:
        response = post_login(client, "nobody@demo.mx", "wrong-password")
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    def test_too_many_attempts_is_login_locked(self, client: TestClient, two_businesses) -> None:
        for _ in range(5):
            post_login(client, "admin.a@demo.mx", "wrong-password")
        response = post_login(client, "admin.a@demo.mx", "wrong-password")
        assert response.status_code == 429
        assert response.json()["code"] == "login_locked"
        assert int(response.headers["Retry-After"]) > 0

    def test_inactive_user_is_user_inactive(
        self, client: TestClient, make_business, make_user
    ) -> None:
        make_user("off@demo.mx", business=make_business(), is_active=False)
        response = post_login(client, "off@demo.mx")
        assert response.status_code == 403
        assert response.json() == {"detail": "Inactive user", "code": "user_inactive"}

    def test_suspended_business_is_business_suspended(
        self, client: TestClient, make_business, make_user
    ) -> None:
        business = make_business("Closed", status=BusinessStatus.SUSPENDED)
        make_user("suspended@demo.mx", business=business)
        response = post_login(client, "suspended@demo.mx")
        assert response.status_code == 403
        assert response.json() == {"detail": "Business suspended", "code": "business_suspended"}


class TestSessionCodes:
    def test_without_session_is_not_authenticated(self, client: TestClient) -> None:
        response = client.get(ME_URL)
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_garbage_token_is_not_authenticated(self, client: TestClient) -> None:
        response = client.get(ME_URL, headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"

    def test_revoked_token_is_not_authenticated(self, client: TestClient, two_businesses) -> None:
        token = login(client, "admin.a@demo.mx")
        client.post("/api/v1/auth/logout")
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"

    def test_open_session_of_suspended_business(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        login(client, "admin.a@demo.mx")
        business = two_businesses["business_a"]
        business.status = BusinessStatus.SUSPENDED
        session.add(business)
        session.commit()
        response = client.get(ME_URL)
        assert response.status_code == 403
        assert response.json()["code"] == "business_suspended"


class TestUserCodes:
    def test_duplicate_email_is_email_taken(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(
            USER_CREATE_URL,
            json={
                "name": "Otra Persona",
                "email": "employee.a@demo.mx",
                "password": "password123",
                "role": Role.EMPLOYEE,
            },
        )
        assert response.status_code == 409
        assert response.json() == {"detail": "Email already in use", "code": "email_taken"}


class TestShapeOfOtherErrors:
    def test_field_validation_keeps_fastapi_shape(self, client: TestClient) -> None:
        response = client.post(LOGIN_URL, data={})
        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], list)
        assert "code" not in body

    def test_errors_outside_the_contract_have_no_code(
        self, client: TestClient, two_businesses
    ) -> None:
        login(client, "employee.a@demo.mx")
        response = client.get("/api/v1/user/list")
        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied"}
