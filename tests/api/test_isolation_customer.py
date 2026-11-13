"""Mandatory MVP test for customers: one business never sees or changes another's."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Customer, Tier, TierFinish
from tests.conftest import login

BASE = "/api/v1/customer"


@pytest.fixture
def data(session: Session, two_businesses) -> dict:
    def tier(key: str, name: str) -> Tier:
        row = Tier(
            business_id=two_businesses[key].id,
            name=name,
            finish=TierFinish.GOLD,
            price_cents=0,
            discount_percent=Decimal("10"),
            points_per_ten=1,
            cashback_percent=Decimal("1"),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    def customer(key: str, tier_row: Tier, name: str, code: str, email: str) -> Customer:
        now = datetime.now(UTC)
        row = Customer(
            business_id=two_businesses[key].id,
            tier_id=tier_row.id,
            code=code,
            full_name=name,
            email=email,
            issued_at=now,
            valid_until=now + timedelta(days=365),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    tier_a, tier_b = tier("business_a", "Oro A"), tier("business_b", "Oro B")
    return {
        "tier_a": tier_a,
        "tier_b": tier_b,
        "a": customer("business_a", tier_a, "Cliente Alfa", "MP-AAAAA", "alfa@correo.com"),
        # Same email as A on purpose: unique per business, not global.
        "b": customer("business_b", tier_b, "Cliente Beta", "MP-BBBBB", "alfa@correo.com"),
    }


def test_list_has_zero_rows_of_the_other_business(client: TestClient, data) -> None:
    login(client, "admin.a@demo.mx")
    body = client.get(f"{BASE}/list", params={"page_size": 500}).json()
    assert [c["full_name"] for c in body["items"]] == ["Cliente Alfa"]
    assert body["total"] == 1


def test_search_does_not_reach_the_other_business(client: TestClient, data) -> None:
    login(client, "admin.a@demo.mx")
    for q in ("Beta", "MP-BBBBB"):
        assert client.get(f"{BASE}/list", params={"q": q}).json()["total"] == 0


def test_summary_counts_only_its_business(client: TestClient, data) -> None:
    login(client, "admin.b@demo.mx")
    assert client.get(f"{BASE}/summary").json()["all"] == 1


def test_lookup_of_other_business_code_is_404(client: TestClient, data) -> None:
    login(client, "employee.a@demo.mx")
    response = client.get(f"{BASE}/lookup", params={"code": "MP-BBBBB"})
    assert response.status_code == 404
    assert response.json()["code"] == "customer_not_found"


def test_detail_of_other_business_looks_like_nonexistent(client: TestClient, data) -> None:
    login(client, "admin.a@demo.mx")
    other = client.get(f"{BASE}/{data['b'].id}")
    missing = client.get(f"{BASE}/999999")
    assert other.status_code == 404
    assert (other.status_code, other.json()) == (missing.status_code, missing.json())


def test_update_and_cancel_of_other_business_are_404_and_unchanged(
    client: TestClient, session: Session, data
) -> None:
    login(client, "admin.a@demo.mx")
    target = data["b"]
    assert (
        client.patch(f"{BASE}/{target.id}/update", json={"full_name": "Hackeado"}).status_code
        == 404
    )
    assert client.post(f"{BASE}/{target.id}/cancel").status_code == 404

    session.expire_all()
    unchanged = session.get(Customer, target.id)
    assert (unchanged.full_name, unchanged.cancelled_at) == ("Cliente Beta", None)


def test_cannot_assign_a_tier_of_the_other_business(client: TestClient, data) -> None:
    login(client, "admin.a@demo.mx")
    create = client.post(
        f"{BASE}/create",
        json={
            "full_name": "Nuevo Cliente",
            "email": "nuevo@correo.com",
            "level_id": data["tier_b"].id,
        },
    )
    update = client.patch(f"{BASE}/{data['a'].id}/update", json={"level_id": data["tier_b"].id})
    assert (create.status_code, update.status_code) == (422, 422)


def test_level_filter_with_other_business_tier_is_empty(client: TestClient, data) -> None:
    login(client, "admin.a@demo.mx")
    params = {"level_id": data["tier_b"].id}
    assert client.get(f"{BASE}/list", params=params).json()["total"] == 0


def test_tier_counts_only_its_customers(client: TestClient, data) -> None:
    login(client, "admin.a@demo.mx")
    counts = [t["customers_count"] for t in client.get("/api/v1/tier/list").json()]
    assert counts == [1]
