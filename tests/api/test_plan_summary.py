"""The plan seen by the business (/plan/summary) and assigned by the platform (issue #70)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Business, BusinessStatus, Role
from services import plan_service
from services.plan_service import utc_now
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

SUMMARY = "/api/v1/plan/summary"


def plan_id(session: Session, key: str) -> int:
    return plan_service.get_by_key(session, key).id


def update_url(business: Business) -> str:
    return f"/api/v1/platform/business/{business.id}/update"


class TestSummary:
    def test_shape(self, client: TestClient, session: Session, two_businesses) -> None:
        business = two_businesses["business_a"]
        tier = add_tier(session, business, "Oro", 0)
        add_customer(session, business, tier, "Laura Méndez", code="MP-AAAA1")
        add_customer(session, business, tier, "Daniela Vega", code="MP-AAAA2", cancelled=True)
        login(client, "admin.a@demo.mx")
        response = client.get(SUMMARY)
        assert response.status_code == 200
        body = response.json()
        assert body["plan"]["key"] == "chain"
        assert set(body) == {
            "plan",
            "assigned_plan_key",
            "trial_ends_at",
            "trial_active",
            "unit_price_cents",
            "usage",
            "can_change_plan",
        }
        assert body["assigned_plan_key"] == "chain"
        assert (body["trial_ends_at"], body["trial_active"]) == (None, False)
        assert body["usage"] == {
            "customers": {"used": 1, "limit": 3000},
            "users": {"used": 2, "limit": 20},
        }

    def test_trial_in_progress(self, client: TestClient, session: Session, two_businesses):
        business = two_businesses["business_a"]
        business.plan_id = plan_id(session, "business")
        business.trial_ends_at = utc_now() + timedelta(days=10)
        session.add(business)
        session.commit()
        login(client, "admin.a@demo.mx")
        body = client.get(SUMMARY).json()
        assert (body["plan"]["key"], body["trial_active"]) == ("business", True)
        assert body["trial_ends_at"].endswith(("Z", "+00:00"))

    def test_ended_trial_shows_the_default_plan(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        business.plan_id = plan_id(session, "business")
        business.trial_ends_at = utc_now() - timedelta(days=1)
        session.add(business)
        session.commit()
        login(client, "admin.a@demo.mx")
        body = client.get(SUMMARY).json()
        assert (body["plan"]["key"], body["assigned_plan_key"]) == ("free", "business")
        assert body["trial_active"] is False
        assert body["usage"]["customers"]["limit"] == 50

    def test_no_plan_is_the_default(self, client: TestClient, session: Session, two_businesses):
        business = two_businesses["business_a"]
        business.plan_id = None
        session.add(business)
        session.commit()
        login(client, "admin.a@demo.mx")
        body = client.get(SUMMARY).json()
        assert (body["plan"]["key"], body["assigned_plan_key"]) == ("free", None)

    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    def test_only_the_admin(self, client: TestClient, two_businesses, email: str) -> None:
        login(client, email)
        assert client.get(SUMMARY).status_code == 403

    def test_manager_is_403(self, client: TestClient, two_businesses, make_user) -> None:
        make_user("manager.a@demo.mx", business=two_businesses["business_a"], role=Role.MANAGER)
        login(client, "manager.a@demo.mx")
        assert client.get(SUMMARY).status_code == 403

    def test_without_session_is_401(self, client: TestClient) -> None:
        assert client.get(SUMMARY).status_code == 401


class TestPlatformAssign:
    @pytest.fixture(autouse=True)
    def _platform(self, client: TestClient, two_businesses) -> None:
        login(client, "owner@memberplus.mx")

    def test_assigns_a_plan_and_ends_the_trial(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        business.plan_id = plan_id(session, "business")
        business.trial_ends_at = utc_now() + timedelta(days=10)
        session.add(business)
        session.commit()
        response = client.patch(update_url(business), json={"plan_id": plan_id(session, "counter")})
        assert response.status_code == 200
        body = response.json()
        assert (body["plan_key"], body["trial_ends_at"]) == ("counter", None)
        assert body["plan"]["unit_price_cents"] == 19_900
        assert body["status"] == "active"

    def test_hidden_plan_with_agreed_price(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_b"]
        response = client.patch(
            update_url(business),
            json={"plan_id": plan_id(session, "chain"), "unit_price_cents": 65_000},
        )
        body = response.json()
        assert (body["plan_key"], body["plan"]["unit_price_cents"]) == ("chain", 65_000)

    def test_price_alone(self, client: TestClient, session: Session, two_businesses) -> None:
        business = two_businesses["business_a"]
        response = client.patch(update_url(business), json={"unit_price_cents": 0})
        assert response.status_code == 200
        session.refresh(business)
        assert (business.unit_price_cents, business.plan_id) == (0, plan_id(session, "chain"))

    def test_status_and_plan_together(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        response = client.patch(
            update_url(business), json={"status": "suspended", "plan_id": plan_id(session, "free")}
        )
        assert (response.json()["status"], response.json()["plan_key"]) == ("suspended", "free")

    def test_unknown_plan_is_422_and_changes_nothing(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        response = client.patch(update_url(business), json={"status": "suspended", "plan_id": 999})
        assert (response.status_code, response.json()["code"]) == (422, "plan_invalid")
        session.refresh(business)
        assert business.status == BusinessStatus.ACTIVE
        assert business.plan_id == plan_id(session, "chain")

    @pytest.mark.parametrize("body", [{"unit_price_cents": -1}, {"plan_id": None}])
    def test_invalid_body_is_422(self, client: TestClient, two_businesses, body: dict) -> None:
        response = client.patch(update_url(two_businesses["business_a"]), json=body)
        assert response.status_code == 422

    def test_the_new_plan_applies_at_once(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        """Lowering the plan blocks the next export; nothing is deleted."""
        business = two_businesses["business_a"]
        client.patch(update_url(business), json={"plan_id": plan_id(session, "free")})
        client.cookies.clear()
        login(client, "admin.a@demo.mx")
        response = client.get("/api/v1/movement/export")
        assert (response.status_code, response.json()["code"]) == (403, "plan_required")
