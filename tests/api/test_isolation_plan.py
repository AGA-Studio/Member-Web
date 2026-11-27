"""Isolation for /api/v1/plan: a business only sees and changes its own plan.

The route takes no business id: it comes from the token.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from core.config import settings
from models import Business
from services import plan_service
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

SUMMARY = "/api/v1/plan/summary"


def test_usage_of_a_is_invisible_to_b(client: TestClient, session: Session, two_businesses) -> None:
    business_a = two_businesses["business_a"]
    tier = add_tier(session, business_a, "Oro", 0)
    for n in range(3):
        add_customer(session, business_a, tier, f"Cliente {n}", code=f"MP-AAAA{n}")
    login(client, "admin.b@demo.mx")
    # 0 rows of A: B counts none of A's cards.
    assert client.get(SUMMARY).json()["usage"]["customers"]["used"] == 0


def test_each_business_sees_its_own_plan(
    client: TestClient, session: Session, two_businesses
) -> None:
    business_b = two_businesses["business_b"]
    business_b.plan_id = plan_service.get_by_key(session, "counter").id
    session.add(business_b)
    session.commit()
    login(client, "admin.a@demo.mx")
    assert client.get(SUMMARY).json()["plan"]["key"] == "chain"
    client.cookies.clear()
    login(client, "admin.b@demo.mx")
    assert client.get(SUMMARY).json()["plan"]["key"] == "counter"


def test_a_plan_change_only_touches_the_session_business(
    client: TestClient, session: Session, two_businesses, monkeypatch
) -> None:
    """PATCH /plan/update takes no business id: A's change never reaches B."""
    monkeypatch.setattr(settings, "plan_self_service_enabled", True)
    free = plan_service.get_by_key(session, "free").id
    for business in (two_businesses["business_a"], two_businesses["business_b"]):
        business.plan_id = free
        session.add(business)
    session.commit()
    login(client, "admin.a@demo.mx")
    counter = plan_service.get_by_key(session, "counter").id
    assert client.patch("/api/v1/plan/update", json={"plan_id": counter}).status_code == 200
    session.expire_all()
    assert session.get(Business, two_businesses["business_a"].id).plan_id == counter
    business_b = session.get(Business, two_businesses["business_b"].id)
    assert (business_b.plan_id, business_b.unit_price_cents) == (free, None)
