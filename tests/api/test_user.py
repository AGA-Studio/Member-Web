"""Tests for /api/v1/user: permissions, validation and business rules."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Role, User
from tests.conftest import DEFAULT_PASSWORD, LOGIN_URL, login

BASE = "/api/v1/user"
NEW_USER = {"name": "New Employee", "email": "new@demo.mx", "password": "password123"}


def all_endpoints(user_id: int) -> list[tuple[str, str, dict | None]]:
    return [
        ("GET", f"{BASE}/list", None),
        ("POST", f"{BASE}/create", NEW_USER),
        ("GET", f"{BASE}/{user_id}", None),
        ("PATCH", f"{BASE}/{user_id}/update", {"name": "Xavier"}),
    ]


class TestPermissions:
    def test_unauthenticated_requests_are_rejected(
        self, client: TestClient, two_businesses
    ) -> None:
        for method, url, body in all_endpoints(two_businesses["admin_a"].id):
            response = client.request(method, url, json=body)
            assert response.status_code == 401, f"{method} {url}"

    def test_employee_is_forbidden(self, client: TestClient, two_businesses) -> None:
        login(client, "employee.a@demo.mx")
        for method, url, body in all_endpoints(two_businesses["employee_a"].id):
            response = client.request(method, url, json=body)
            assert response.status_code == 403, f"{method} {url}"
            assert response.json()["detail"] == "Permission denied"

    def test_platform_owner_is_forbidden(self, client: TestClient, two_businesses) -> None:
        # The platform owner never manages a business's users.
        login(client, "owner@memberplus.mx")
        for method, url, body in all_endpoints(two_businesses["admin_a"].id):
            assert client.request(method, url, json=body).status_code == 403, f"{method} {url}"


class TestListUsers:
    def test_admin_lists_only_own_business(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/list")
        assert response.status_code == 200
        emails = {u["email"] for u in response.json()}
        assert emails == {"admin.a@demo.mx", "employee.a@demo.mx"}

    def test_response_never_exposes_password_hash(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        for user in client.get(f"{BASE}/list").json():
            assert "hashed_password" not in user


class TestCreateUser:
    def test_create_defaults_to_employee(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json=NEW_USER)
        assert response.status_code == 201
        body = response.json()
        assert body["role"] == "employee"
        assert body["is_active"] is True
        assert body["business_id"] == two_businesses["business_a"].id
        assert "hashed_password" not in body

    def test_create_admin(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "role": "admin"})
        assert response.status_code == 201
        assert response.json()["role"] == "admin"

    def test_created_user_can_login(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        client.post(f"{BASE}/create", json=NEW_USER)
        client.cookies.clear()
        login(client, NEW_USER["email"], NEW_USER["password"])
        assert client.get("/api/v1/auth/me").json()["email"] == NEW_USER["email"]

    def test_password_is_stored_hashed(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        login(client, "admin.a@demo.mx")
        client.post(f"{BASE}/create", json=NEW_USER)
        stored = session.exec(select(User).where(User.email == NEW_USER["email"])).one()
        assert stored.hashed_password.startswith("$argon2id$")
        assert NEW_USER["password"] not in stored.hashed_password

    def test_email_is_normalized_to_lowercase(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "email": "New.Person@Demo.MX"})
        assert response.json()["email"] == "new.person@demo.mx"

    def test_business_id_in_body_is_ignored(self, client: TestClient, two_businesses) -> None:
        # The business always comes from the token, never from the request.
        login(client, "admin.a@demo.mx")
        response = client.post(
            f"{BASE}/create",
            json={**NEW_USER, "business_id": two_businesses["business_b"].id},
        )
        assert response.status_code == 201
        assert response.json()["business_id"] == two_businesses["business_a"].id

    def test_cannot_create_platform_user(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "role": "platform"})
        assert response.status_code == 403
        assert response.json()["detail"] == "Role not allowed"

    def test_duplicate_email(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "email": "employee.a@demo.mx"})
        assert response.status_code == 409

    def test_duplicate_email_ignores_case(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "email": "EMPLOYEE.A@demo.mx"})
        assert response.status_code == 409

    def test_email_is_unique_across_businesses(self, client: TestClient, two_businesses) -> None:
        # Login is by email only, so an email can exist in just one business.
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "email": "admin.b@demo.mx"})
        assert response.status_code == 409

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("email", "not-an-email"),
            ("password", "short"),
            ("password", "x" * 129),
            ("name", ""),
            ("name", "x" * 121),
            ("role", "superuser"),
        ],
        ids=["bad-email", "short-pass", "long-pass", "empty-name", "long-name", "bad-role"],
    )
    def test_validation_errors(
        self, client: TestClient, two_businesses, field: str, value: str
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, field: value})
        assert response.status_code == 422

    def test_name_is_normalized(self, client: TestClient, two_businesses) -> None:
        # H5: spaces are trimmed and collapsed before saving.
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "name": "  José   Luis "})
        assert response.status_code == 201
        assert response.json()["name"] == "José Luis"

    @pytest.mark.parametrize("name", ["   ", "A", "Ana2", "@@@"])
    def test_invalid_names_are_rejected(
        self, client: TestClient, two_businesses, name: str
    ) -> None:
        # H5: at least 2 letters; only letters, spaces, hyphens and apostrophes.
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "name": name})
        assert response.status_code == 422

    @pytest.mark.parametrize("missing", ["name", "email", "password"])
    def test_required_fields(self, client: TestClient, two_businesses, missing: str) -> None:
        login(client, "admin.a@demo.mx")
        body = {k: v for k, v in NEW_USER.items() if k != missing}
        assert client.post(f"{BASE}/create", json=body).status_code == 422


class TestGetUser:
    def test_get_user_of_own_business(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/{two_businesses['employee_a'].id}")
        assert response.status_code == 200
        assert response.json()["email"] == "employee.a@demo.mx"

    def test_get_nonexistent_user(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.get(f"{BASE}/999999")
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    def test_non_numeric_id(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        assert client.get(f"{BASE}/abc").status_code == 422


class TestUpdateUser:
    def url(self, user: User) -> str:
        return f"{BASE}/{user.id}/update"

    def test_update_name(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["employee_a"]), json={"name": "Renamed"})
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        assert response.json()["email"] == "employee.a@demo.mx"  # untouched

    def test_empty_body_changes_nothing(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        before = client.get(f"{BASE}/{two_businesses['employee_a'].id}").json()
        after = client.patch(self.url(two_businesses["employee_a"]), json={}).json()
        assert before == after

    def test_update_password(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        client.patch(self.url(two_businesses["employee_a"]), json={"password": "newpassword1"})
        client.cookies.clear()
        old = client.post(
            LOGIN_URL, data={"username": "employee.a@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert old.status_code == 401
        login(client, "employee.a@demo.mx", "newpassword1")

    def test_update_email(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            self.url(two_businesses["employee_a"]), json={"email": "Cashier@Demo.mx"}
        )
        assert response.json()["email"] == "cashier@demo.mx"

    def test_update_email_to_same_value(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            self.url(two_businesses["employee_a"]), json={"email": "EMPLOYEE.A@demo.mx"}
        )
        assert response.status_code == 200

    def test_update_email_to_taken_value(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            self.url(two_businesses["employee_a"]), json={"email": "admin.b@demo.mx"}
        )
        assert response.status_code == 409

    def test_deactivate_user_blocks_login(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["employee_a"]), json={"is_active": False})
        assert response.json()["is_active"] is False
        client.cookies.clear()
        blocked = client.post(
            LOGIN_URL, data={"username": "employee.a@demo.mx", "password": DEFAULT_PASSWORD}
        )
        assert blocked.status_code == 403

    def test_role_cannot_be_changed(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["employee_a"]), json={"role": "admin"})
        assert response.status_code == 200
        assert response.json()["role"] == "employee"

    def test_business_cannot_be_changed(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            self.url(two_businesses["employee_a"]),
            json={"business_id": two_businesses["business_b"].id},
        )
        assert response.json()["business_id"] == two_businesses["business_a"].id

    def test_blank_name_is_rejected_on_update(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["employee_a"]), json={"name": "   "})
        assert response.status_code == 422

    def test_short_password_is_rejected(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["employee_a"]), json={"password": "short"})
        assert response.status_code == 422

    def test_nonexistent_user(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        assert client.patch(f"{BASE}/999999/update", json={"name": "Xavier"}).status_code == 404

    def test_admin_can_update_self(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["admin_a"]), json={"name": "Me"})
        assert response.status_code == 200

    def test_admin_cannot_deactivate_self(self, client: TestClient, two_businesses) -> None:
        # H3: an admin locking themselves out could leave the business without an admin.
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["admin_a"]), json={"is_active": False})
        assert response.status_code == 400
        assert response.json()["detail"] == "You cannot deactivate your own account"
        assert client.get("/api/v1/auth/me").json()["is_active"] is True

    def test_admin_can_send_is_active_true_for_self(
        self, client: TestClient, two_businesses
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(self.url(two_businesses["admin_a"]), json={"is_active": True})
        assert response.status_code == 200

    def test_admin_can_deactivate_another_admin(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        other = client.post(
            f"{BASE}/create",
            json={
                "name": "Second Admin",
                "email": "admin2@demo.mx",
                "password": "password123",
                "role": "admin",
            },
        ).json()
        response = client.patch(f"{BASE}/{other['id']}/update", json={"is_active": False})
        assert response.status_code == 200
        assert response.json()["is_active"] is False


def test_admin_without_business_is_rejected(client: TestClient, make_user) -> None:
    """Inconsistent data guard: an admin must belong to a business (dependency BusinessId)."""
    make_user("orphan@demo.mx", business=None, role=Role.ADMIN)
    login(client, "orphan@demo.mx")
    response = client.get("/api/v1/user/list")
    assert response.status_code == 403
    assert response.json()["detail"] == "This user does not belong to a business"


class TestEmailRace:
    """H6: two requests that pass the email check at the same time.

    The pre-check is disabled to reproduce the race deterministically: only the
    unique index on users.email stops the duplicate, and the API must answer 409.
    """

    @pytest.fixture(autouse=True)
    def _skip_email_precheck(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("api.v1.user_api._ensure_email_available", lambda *_: None)

    def test_create_duplicate_returns_409_not_500(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(f"{BASE}/create", json={**NEW_USER, "email": "employee.a@demo.mx"})
        assert response.status_code == 409
        assert response.json()["detail"] == "Email already in use"

    def test_update_to_taken_email_returns_409_not_500(
        self, client: TestClient, two_businesses
    ) -> None:
        login(client, "admin.a@demo.mx")
        response = client.patch(
            f"{BASE}/{two_businesses['employee_a'].id}/update", json={"email": "admin.b@demo.mx"}
        )
        assert response.status_code == 409

    def test_failed_update_leaves_user_unchanged(self, client: TestClient, two_businesses) -> None:
        login(client, "admin.a@demo.mx")
        user_id = two_businesses["employee_a"].id
        client.patch(
            f"{BASE}/{user_id}/update", json={"name": "Changed", "email": "admin.b@demo.mx"}
        )
        body = client.get(f"{BASE}/{user_id}").json()
        assert body["email"] == "employee.a@demo.mx"
        assert body["name"] == "Test User"

    def test_api_keeps_working_after_the_conflict(self, client: TestClient, two_businesses) -> None:
        # The session is rolled back, so the next request is not stuck in a failed transaction.
        login(client, "admin.a@demo.mx")
        client.post(f"{BASE}/create", json={**NEW_USER, "email": "employee.a@demo.mx"})
        response = client.post(f"{BASE}/create", json=NEW_USER)
        assert response.status_code == 201
