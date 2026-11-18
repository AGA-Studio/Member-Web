"""Isolation for /api/v1/business: an admin only changes their own business.

The route takes no business id: the business comes from the token. These tests
prove that a change by A never reaches B, and that a body can't redirect it.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Business
from tests.conftest import login

URL = "/api/v1/business/update"


def reload(session: Session, business: Business) -> Business:
    session.refresh(business)
    return business


def test_change_by_a_never_reaches_b(client: TestClient, session: Session, two_businesses) -> None:
    login(client, "admin.a@demo.mx")
    client.patch(URL, json={"name": "Café Aurora", "validity_months": 6})

    b = reload(session, two_businesses["business_b"])
    assert (b.name, b.validity_months) == ("Business B", 12)

    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    # 0 rows of A: B's session shows its own business, untouched.
    assert client.get("/api/v1/auth/me").json()["business"]["name"] == "Business B"


def test_business_id_in_the_body_is_ignored(
    client: TestClient, session: Session, two_businesses
) -> None:
    login(client, "admin.a@demo.mx")
    b_id = two_businesses["business_b"].id
    response = client.patch(URL, json={"id": b_id, "business_id": b_id, "name": "Tomado"})
    assert response.json()["id"] == two_businesses["business_a"].id
    assert reload(session, two_businesses["business_b"]).name == "Business B"
    assert reload(session, two_businesses["business_a"]).name == "Tomado"
