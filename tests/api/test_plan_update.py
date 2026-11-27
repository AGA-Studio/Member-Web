"""PATCH /api/v1/plan/update: the admin changes their own business's plan.

Acceptance criteria of the wiki page "Cambio de plan desde el panel:
especificación para el backend". The payment is simulated in the frontend, so
the route is behind `PLAN_SELF_SERVICE_ENABLED` (off by default).
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.config import settings
from models import Business, BusinessStatus, Role
from services import plan_service
from services.plan_service import utc_now
from tests.conftest import login

URL = "/api/v1/plan/update"
SUMMARY = "/api/v1/plan/summary"
ADMIN = "admin.a@demo.mx"
NEW_USER = {"name": "New Employee", "email": "new@demo.mx", "password": "password123"}


def plan_id(session: Session, key: str) -> int:
    return plan_service.get_by_key(session, key).id


def set_plan(
    session: Session, business: Business, key: str | None, trial_ends_at: datetime | None = None
) -> None:
    business.plan_id = plan_id(session, key) if key else None
    business.trial_ends_at = trial_ends_at
    session.add(business)
    session.commit()


def change(client: TestClient, session: Session, key: str):
    return client.patch(URL, json={"plan_id": plan_id(session, key)})


@pytest.fixture
def self_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "plan_self_service_enabled", True)


@pytest.mark.usefixtures("self_service")
class TestChange:
    def test_free_to_business_applies_the_limits_at_once(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free")
        login(client, ADMIN)
        # Free: 2 users (both in use) and no exports.
        assert client.post("/api/v1/user/create", json=NEW_USER).status_code == 409
        response = change(client, session, "business")
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["plan"]["key"], body["assigned_plan_key"]) == ("business", "business")
        assert (body["trial_ends_at"], body["trial_active"]) == (None, False)
        assert body["unit_price_cents"] == 39_900
        assert body["usage"]["users"] == {"used": 2, "limit": 8}
        assert body["can_change_plan"] is True
        assert client.post("/api/v1/user/create", json=NEW_USER).status_code == 201
        assert client.get("/api/v1/movement/export").status_code == 200

    def test_response_is_the_summary(self, client: TestClient, session: Session, two_businesses):
        set_plan(session, two_businesses["business_a"], "free")
        login(client, ADMIN)
        changed = change(client, session, "counter").json()
        assert changed == client.get(SUMMARY).json()

    def test_changing_during_the_trial_ends_it(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "business", utc_now() + timedelta(days=10))
        login(client, ADMIN)
        body = change(client, session, "counter").json()
        assert (body["plan"]["key"], body["trial_ends_at"]) == ("counter", None)
        assert body["unit_price_cents"] == 19_900
        session.refresh(business)
        assert (business.trial_ends_at, business.unit_price_cents) == (None, 19_900)

    def test_the_trial_plan_itself_is_contracted(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "business", utc_now() + timedelta(days=10))
        login(client, ADMIN)
        response = change(client, session, "business")
        assert response.status_code == 200
        body = response.json()
        assert (body["plan"]["key"], body["trial_ends_at"]) == ("business", None)
        assert body["unit_price_cents"] == 39_900
        # No second trial: the plan is contracted now, so asking again is 409.
        assert change(client, session, "business").json()["code"] == "plan_unchanged"

    def test_after_an_ended_trial_the_plan_can_be_contracted(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "business", utc_now() - timedelta(days=1))
        login(client, ADMIN)
        assert client.get(SUMMARY).json()["plan"]["key"] == "free"
        response = change(client, session, "business")
        assert response.status_code == 200
        assert (response.json()["plan"]["key"], response.json()["trial_active"]) == (
            "business",
            False,
        )

    def test_without_a_plan_any_public_plan(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], None)
        login(client, ADMIN)
        assert client.get(SUMMARY).json()["can_change_plan"] is True
        assert change(client, session, "free").json()["assigned_plan_key"] == "free"

    def test_lowering_over_the_limit_deletes_nothing(
        self, client: TestClient, session: Session, two_businesses, make_user
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "business")
        make_user("third.a@demo.mx", business=business, role=Role.EMPLOYEE)
        login(client, ADMIN)
        response = change(client, session, "free")
        assert response.status_code == 200
        # 3 active users on a plan of 2: all of them stay active.
        assert response.json()["usage"]["users"] == {"used": 3, "limit": 2}
        response = client.post("/api/v1/user/create", json=NEW_USER)
        assert (response.status_code, response.json()["code"]) == (409, "limit_reached")
        response = client.get("/api/v1/movement/export")
        assert (response.status_code, response.json()["code"]) == (403, "plan_required")

    def test_the_same_plan_without_trial_is_409(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "counter")
        business.unit_price_cents = 15_000
        session.add(business)
        session.commit()
        login(client, ADMIN)
        response = change(client, session, "counter")
        assert (response.status_code, response.json()["code"]) == (409, "plan_unchanged")
        session.refresh(business)
        assert business.unit_price_cents == 15_000

    @pytest.mark.parametrize("key", ["chain", None])
    def test_hidden_or_missing_plan_is_422(
        self, client: TestClient, session: Session, two_businesses, key: str | None
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "free")
        login(client, ADMIN)
        target = plan_id(session, key) if key else 999_999
        response = client.patch(URL, json={"plan_id": target})
        assert (response.status_code, response.json()["code"]) == (422, "plan_invalid")
        session.refresh(business)
        assert business.plan_id == plan_id(session, "free")

    @pytest.mark.parametrize("body", [{}, {"plan_id": "gold"}, {"plan_id": None}])
    def test_invalid_body_is_422(
        self, client: TestClient, session: Session, two_businesses, body: dict
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free")
        login(client, ADMIN)
        response = client.patch(URL, json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_a_hidden_plan_cannot_be_left_alone(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        """Business A is on Cadena (hidden, assigned by hand)."""
        business = two_businesses["business_a"]
        login(client, ADMIN)
        assert client.get(SUMMARY).json()["can_change_plan"] is False
        response = change(client, session, "business")
        assert (response.status_code, response.json()["code"]) == (403, "plan_change_closed")
        session.refresh(business)
        assert business.plan_id == plan_id(session, "chain")


class TestSwitchedOff:
    def test_off_by_default(self) -> None:
        assert type(settings).model_fields["plan_self_service_enabled"].default is False

    def test_closed_and_hidden_button(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "free")
        login(client, ADMIN)
        assert client.get(SUMMARY).json()["can_change_plan"] is False
        response = change(client, session, "business")
        assert (response.status_code, response.json()["code"]) == (403, "plan_change_closed")
        session.refresh(business)
        assert business.plan_id == plan_id(session, "free")

    def test_closed_comes_before_the_body(self, client: TestClient, two_businesses) -> None:
        login(client, ADMIN)
        response = client.patch(URL, json={})
        assert (response.status_code, response.json()["code"]) == (403, "plan_change_closed")


@pytest.mark.usefixtures("self_service")
class TestAccess:
    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    def test_without_business_manage_is_403(
        self, client: TestClient, session: Session, two_businesses, email: str
    ) -> None:
        login(client, email)
        response = change(client, session, "free")
        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied"}

    def test_manager_is_403(
        self, client: TestClient, session: Session, two_businesses, make_user
    ) -> None:
        make_user("manager.a@demo.mx", business=two_businesses["business_a"], role=Role.MANAGER)
        login(client, "manager.a@demo.mx")
        assert change(client, session, "free").status_code == 403

    def test_permission_comes_before_the_body(self, client: TestClient, two_businesses) -> None:
        login(client, "employee.a@demo.mx")
        assert client.patch(URL, json={}).status_code == 403

    def test_without_session_is_401(self, client: TestClient, session: Session) -> None:
        assert client.patch(URL, json={"plan_id": plan_id(session, "free")}).status_code == 401

    def test_suspended_business_is_403(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "free")
        login(client, ADMIN)
        business.status = BusinessStatus.SUSPENDED
        session.add(business)
        session.commit()
        response = change(client, session, "business")
        assert (response.status_code, response.json()["code"]) == (403, "business_suspended")
        session.refresh(business)
        assert business.plan_id == plan_id(session, "free")
