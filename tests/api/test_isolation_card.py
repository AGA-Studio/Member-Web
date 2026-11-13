"""Isolation of the card link: business B can never create A's link."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import CardDelivery
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

BASE = "/api/v1/customer"


@pytest.fixture
def customer_a(session: Session, two_businesses):
    business = two_businesses["business_a"]
    return add_customer(
        session, business, add_tier(session, business, "Oro", 0), "Laura Méndez", code="MP-AAAA1"
    )


@pytest.mark.parametrize("action", ["card-link"])
def test_admin_b_gets_404_for_a_customer_of_a(
    client: TestClient, session: Session, customer_a, action: str
) -> None:
    login(client, "admin.b@demo.mx")
    response = client.post(f"{BASE}/{customer_a.id}/{action}")
    assert response.status_code == 404
    assert response.json()["code"] == "customer_not_found"
    assert not session.exec(select(CardDelivery)).all()


def test_a_link_of_a_shows_only_a(client: TestClient, customer_a) -> None:
    login(client, "admin.a@demo.mx")
    token = client.post(f"{BASE}/{customer_a.id}/card-link").json()["url"].rsplit("/", 1)[1]
    login(client, "admin.b@demo.mx")
    assert client.get(f"/api/v1/card/{token}").json()["business"]["name"] == "Business A"
