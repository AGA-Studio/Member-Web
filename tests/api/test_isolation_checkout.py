"""Mandatory MVP test for the checkout: one business never charges or reads another's."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Purchase, TierFinish
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

BASE = "/api/v1/checkout"


@pytest.fixture
def data(session: Session, two_businesses) -> dict:
    tier_a = add_tier(session, two_businesses["business_a"], "Oro A", 0, finish=TierFinish.GOLD)
    tier_b = add_tier(session, two_businesses["business_b"], "Oro B", 0, finish=TierFinish.GOLD)
    return {
        "a": add_customer(
            session, two_businesses["business_a"], tier_a, "Cliente Alfa", code="MP-AAAAA"
        ),
        "b": add_customer(
            session, two_businesses["business_b"], tier_b, "Cliente Beta", code="MP-BBBBB"
        ),
    }


def test_cannot_charge_a_customer_of_the_other_business(
    client: TestClient, session: Session, data
) -> None:
    login(client, "employee.a@demo.mx")
    body = {"customer_id": data["b"].id, "amount_cents": 10_000}
    for action in ("create", "preview"):
        response = client.post(f"{BASE}/{action}", json=body)
        assert (response.status_code, response.json()["code"]) == (404, "customer_not_found")
    assert session.exec(select(Purchase)).all() == []


def test_receipt_of_the_other_business_looks_like_nonexistent(client: TestClient, data) -> None:
    login(client, "admin.b@demo.mx")
    receipt_id = client.post(
        f"{BASE}/create", json={"customer_id": data["b"].id, "amount_cents": 10_000}
    ).json()["id"]
    login(client, "admin.a@demo.mx")
    other = client.get(f"{BASE}/{receipt_id}")
    missing = client.get(f"{BASE}/999999")
    assert other.status_code == 404
    assert other.json() == missing.json()


def test_balances_count_zero_rows_of_the_other_business(client: TestClient, data) -> None:
    login(client, "admin.b@demo.mx")
    client.post(f"{BASE}/create", json={"customer_id": data["b"].id, "amount_cents": 100_000})
    login(client, "admin.a@demo.mx")
    customer = client.get(f"/api/v1/customer/{data['a'].id}").json()
    assert (customer["points_balance"], customer["cashback_balance_cents"]) == (0, 0)


def test_idempotency_keys_are_per_business(client: TestClient, session: Session, data) -> None:
    headers = {"Idempotency-Key": "same-key"}
    login(client, "employee.a@demo.mx")
    a = client.post(
        f"{BASE}/create", json={"customer_id": data["a"].id, "amount_cents": 1_000}, headers=headers
    )
    login(client, "employee.b@demo.mx")
    b = client.post(
        f"{BASE}/create", json={"customer_id": data["b"].id, "amount_cents": 1_000}, headers=headers
    )
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["id"] != b.json()["id"]
    assert len(session.exec(select(Purchase)).all()) == 2
