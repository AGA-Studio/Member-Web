"""Isolation for /api/v1/plan/summary: a business only sees its own plan and usage.

The route takes no business id: it comes from the token.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

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
