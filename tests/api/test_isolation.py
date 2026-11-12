"""Mandatory MVP test: one business never sees or changes another business's data.

MVP acceptance criterion: "0 rows from another business, verified by an
automated test".
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import User
from tests.conftest import login

BASE = "/api/v1/user"


def test_admin_a_sees_zero_rows_of_business_b(client: TestClient, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    rows = client.get(f"{BASE}/list").json()
    business_b = two_businesses["business_b"].id
    assert [r for r in rows if r["business_id"] == business_b] == []


def test_admin_b_sees_zero_rows_of_business_a(client: TestClient, two_businesses) -> None:
    login(client, "admin.b@demo.mx")
    rows = client.get(f"{BASE}/list").json()
    assert {r["email"] for r in rows} == {"admin.b@demo.mx", "employee.b@demo.mx"}


def test_get_user_of_other_business_returns_404(client: TestClient, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    for key in ("admin_b", "employee_b"):
        response = client.get(f"{BASE}/{two_businesses[key].id}")
        # 404 (not 403): the API does not reveal that the user exists.
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"


def test_other_business_and_nonexistent_look_identical(client: TestClient, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    other = client.get(f"{BASE}/{two_businesses['admin_b'].id}")
    missing = client.get(f"{BASE}/999999")
    assert (other.status_code, other.json()) == (missing.status_code, missing.json())


def test_update_user_of_other_business_is_rejected_and_unchanged(
    client: TestClient, session: Session, two_businesses
) -> None:
    login(client, "admin.a@demo.mx")
    target = two_businesses["employee_b"]
    response = client.patch(
        f"{BASE}/{target.id}/update",
        json={"name": "Hacked", "is_active": False, "password": "hacked123"},
    )
    assert response.status_code == 404

    session.expire_all()
    unchanged = session.get(User, target.id)
    assert unchanged.name == "Test User"
    assert unchanged.is_active is True


def test_user_created_by_a_is_invisible_to_b(client: TestClient, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    created = client.post(
        f"{BASE}/create",
        json={"name": "Only A", "email": "only.a@demo.mx", "password": "password123"},
    ).json()

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    assert "only.a@demo.mx" not in {u["email"] for u in client.get(f"{BASE}/list").json()}
    assert client.get(f"{BASE}/{created['id']}").status_code == 404


def test_forged_business_id_in_token_body_has_no_effect(client: TestClient, two_businesses) -> None:
    """Even a token claiming business B is scoped by the user's real business in the DB."""
    from core.security import create_access_token

    token = create_access_token(
        user_id=two_businesses["admin_a"].id,
        role="admin",
        business_id=two_businesses["business_b"].id,  # lie
    )
    rows = client.get(f"{BASE}/list", headers={"Authorization": f"Bearer {token}"}).json()
    assert {r["business_id"] for r in rows} == {two_businesses["business_a"].id}
