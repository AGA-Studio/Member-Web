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
    def add(business_key: str, name: str, min_points: int) -> Tier:
        tier = Tier(
            business_id=two_businesses[business_key].id,
            name=name,
            finish=TierFinish.GOLD,
            min_points=min_points,
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
        "a_top": add("business_a", "Top A", 500),
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


def test_thresholds_of_other_business_do_not_count(client: TestClient, tiers) -> None:
    """The min_points rules only look at the tiers of the same business."""
    login(client, "admin.b@demo.mx")
    target = tiers["b_base"]
    # A also has a tier at 0 points: it does not count as a clash for B.
    assert client.patch(f"{BASE}/{target.id}/update", json={"min_points": 0}).status_code == 200
    # A's tier at 0 does not cover B either: B's only tier must stay at 0.
    response = client.patch(f"{BASE}/{target.id}/update", json={"min_points": 500})
    assert response.status_code == 422
    assert response.json()["code"] == "tier_invalid"
