"""Mandatory MVP test for tiers: one business never sees or edits another's."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Tier, TierFinish
from tests.conftest import login

BASE = "/api/v1/tier"


@pytest.fixture
def tiers(session: Session, two_businesses) -> dict[str, Tier]:
    def add(business_key: str, name: str, price_cents: int) -> Tier:
        tier = Tier(
            business_id=two_businesses[business_key].id,
            name=name,
            finish=TierFinish.GOLD,
            price_cents=price_cents,
            discount_percent=Decimal("10"),
            points_per_ten=1,
            cashback_percent=Decimal("1"),
        )
        session.add(tier)
        session.commit()
        session.refresh(tier)
        return tier

    return {
        "a_base": add("business_a", "Base A", 0),
        "a_top": add("business_a", "Top A", 50_000),
        "b_base": add("business_b", "Base B", 0),
    }


def test_each_business_sees_only_its_tiers(client: TestClient, tiers) -> None:
    login(client, "employee.a@demo.mx")
    assert {t["name"] for t in client.get(f"{BASE}/list").json()} == {"Base A", "Top A"}

    client.cookies.clear()
    login(client, "employee.b@demo.mx")
    assert {t["name"] for t in client.get(f"{BASE}/list").json()} == {"Base B"}


def test_update_tier_of_other_business_is_404_and_unchanged(
    client: TestClient, session: Session, tiers
) -> None:
    login(client, "admin.a@demo.mx")
    target = tiers["b_base"]
    response = client.patch(f"{BASE}/{target.id}/update", json={"discount_percent": 99})
    assert response.status_code == 404

    session.expire_all()
    assert session.get(Tier, target.id).discount_percent == Decimal("10")


def test_other_business_and_nonexistent_look_identical(client: TestClient, tiers) -> None:
    login(client, "admin.a@demo.mx")
    other = client.patch(f"{BASE}/{tiers['b_base'].id}/update", json={"name": "X"})
    missing = client.patch(f"{BASE}/999999/update", json={"name": "X"})
    assert (other.status_code, other.json()) == (missing.status_code, missing.json())


def test_editing_own_tier_leaves_other_business_untouched(
    client: TestClient, session: Session, tiers
) -> None:
    login(client, "admin.b@demo.mx")
    target = tiers["b_base"]
    response = client.patch(f"{BASE}/{target.id}/update", json={"price_cents": 99_900})
    assert response.status_code == 200

    session.expire_all()
    assert session.get(Tier, tiers["a_base"].id).price_cents == 0
    assert session.get(Tier, tiers["a_top"].id).price_cents == 50_000
