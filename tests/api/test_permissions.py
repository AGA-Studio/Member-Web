"""Permissions by role (core/permissions.py, issue #72).

Every route that asks for a permission is called once per role: the roles that
lack it get 403, the rest get past the check (whatever the
route answers next: 200, 404 or 422 for the empty body). The route list is read
from the app, so a new route is covered without touching this file.
"""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from core.permissions import ROLE_PERMISSIONS, Permission, has_permission, permissions_of
from main import API_V1_PREFIX, API_V1_ROUTERS
from models.user_model import Role
from tests.api.test_checkout import cards, charge, gold  # noqa: F401  (fixtures)
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

EMAILS = {
    Role.PLATFORM: "owner@memberplus.mx",
    Role.ADMIN: "admin.a@demo.mx",
    Role.MANAGER: "manager.a@demo.mx",
    Role.EMPLOYEE: "employee.a@demo.mx",
}


def _permission_of(dependant) -> Permission | None:
    permission = getattr(dependant.call, "permission", None)
    if permission is not None:
        return permission
    for sub in dependant.dependencies:
        found = _permission_of(sub)
        if found is not None:
            return found
    return None


def guarded_routes() -> list[tuple[str, str, Permission]]:
    """(method, path, permission) of every v1 route guarded by `require_permission`."""
    routes = []
    for router in API_V1_ROUTERS:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            permission = _permission_of(route.dependant)
            if permission is None:
                continue
            path = API_V1_PREFIX + re.sub(r"\{[^}]+\}", "999999", route.path)
            for method in sorted(route.methods):
                routes.append((method, path, permission))
    return routes


GUARDED = guarded_routes()


def _past_the_permission(response) -> bool:
    """A 403 that a route raises only once the permission check passed."""
    return response.json().get("code") == "plan_change_closed"


# Not a route of its own: it widens what CHECKOUT reads (checkout_service.get_receipt).
NOT_A_ROUTE = {Permission.RECEIPTS_ALL}


@pytest.fixture
def staff(two_businesses, make_user) -> dict:
    manager = make_user(
        "manager.a@demo.mx", business=two_businesses["business_a"], role=Role.MANAGER
    )
    return {**two_businesses, "manager_a": manager}


def test_every_role_has_an_entry() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_the_routes_were_found() -> None:
    permissions = {permission for _, _, permission in GUARDED}
    assert permissions == set(Permission) - NOT_A_ROUTE, (
        f"Permissions no route asks for: {set(Permission) - NOT_A_ROUTE - permissions}"
    )
    assert len(GUARDED) > 30


@pytest.mark.parametrize("role", list(Role))
def test_each_route_answers_by_the_matrix(client: TestClient, staff, role: Role) -> None:
    login(client, EMAILS[role])
    wrong = []
    for method, path, permission in GUARDED:
        response = client.request(method, path)
        # Any 403: on some routes `BusinessId` stops the platform owner before the check.
        # `plan_change_closed` comes after the permission (PATCH /plan/update, switch off).
        denied = response.status_code == 403 and not _past_the_permission(response)
        if denied == has_permission(role, permission):
            wrong.append(f"{method} {path} ({permission}): {response.status_code}")
    assert not wrong, f"{role} got the wrong answer on:\n" + "\n".join(wrong)


class TestManager:
    def test_me_lists_the_permissions(self, client: TestClient, staff) -> None:
        login(client, "manager.a@demo.mx")
        body = client.get("/api/v1/auth/me").json()
        assert body["role"] == "manager"
        assert body["permissions"] == permissions_of(Role.MANAGER)
        assert "customers.manage" in body["permissions"]
        assert "users.manage" not in body["permissions"]

    def test_admin_creates_a_manager(self, client: TestClient, staff) -> None:
        login(client, "admin.a@demo.mx")
        response = client.post(
            "/api/v1/user/create",
            json={
                "name": "Marta Ruiz",
                "email": "marta@demo.mx",
                "password": "password123",
                "role": "manager",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["role"] == "manager"
        login(client, "marta@demo.mx")
        assert client.get("/api/v1/customer/list").status_code == 200
        assert client.get("/api/v1/user/list").status_code == 403

    def test_manager_reads_every_receipt(self, client: TestClient, staff, cards) -> None:  # noqa: F811
        login(client, "employee.a@demo.mx")
        receipt_id = charge(client, cards["active"].id).json()["id"]
        login(client, "manager.a@demo.mx")
        assert client.get(f"/api/v1/checkout/{receipt_id}").status_code == 200

    def test_manager_cannot_edit_tiers_or_the_business(self, client: TestClient, staff) -> None:
        login(client, "manager.a@demo.mx")
        assert client.get("/api/v1/tier/list").status_code == 200
        assert client.patch("/api/v1/tier/1/update", json={}).status_code == 403
        assert client.patch("/api/v1/business/update", json={}).status_code == 403

    def test_manager_does_not_see_another_business(
        self,
        client: TestClient,
        session,
        staff,
        cards,  # noqa: F811
    ) -> None:
        business_b = staff["business_b"]
        tier_b = add_tier(session, business_b, "Oro B", 0)
        other = add_customer(session, business_b, tier_b, "Pedro Ruiz", code="MP-BBBB1")
        login(client, "manager.a@demo.mx")
        names = [c["full_name"] for c in client.get("/api/v1/customer/list").json()["items"]]
        assert "Laura Méndez" in names
        assert "Pedro Ruiz" not in names
        assert client.get(f"/api/v1/customer/{other.id}").status_code == 404
        assert client.get("/api/v1/customer/lookup", params={"code": "MP-BBBB1"}).status_code == 404
