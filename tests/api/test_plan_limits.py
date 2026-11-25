"""What each plan allows (services/plan_service.py, issue #70).

Capacity over the limit is 409 `limit_reached`; a feature outside the plan is
403 `plan_required`. The plan is the effective one: an ended trial is the free plan.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.v1.dependencies import require_plan_feature
from models import Business, Customer, Tier, User
from services import plan_service
from services.plan_service import utc_now
from tests.api.test_customer import add_customer, add_tier, new_customer
from tests.api.test_movement import charge
from tests.conftest import login, make_image

ADMIN = "admin.a@demo.mx"


def set_plan(session: Session, business: Business, key: str, **plan_changes) -> None:
    plan = plan_service.get_by_key(session, key)
    for field, value in plan_changes.items():
        setattr(plan, field, value)
    business.plan_id = plan.id
    business.trial_ends_at = None
    session.add_all([plan, business])
    session.commit()


@pytest.fixture
def tier(session: Session, two_businesses) -> Tier:
    return add_tier(session, two_businesses["business_a"], "Oro", 0)


def fill_customers(session: Session, business: Business, tier: Tier, count: int) -> list[Customer]:
    return [
        add_customer(session, business, tier, f"Cliente {n:03d}", code=f"MP-{n:05d}")
        for n in range(count)
    ]


def error_code(response) -> str:
    return response.json().get("code")


class TestCustomerCapacity:
    def test_create_up_to_the_limit_then_409(
        self, client: TestClient, session: Session, two_businesses, tier
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "free", max_customers=2)
        fill_customers(session, business, tier, 1)
        login(client, ADMIN)
        assert client.post("/api/v1/customer/create", json=new_customer()).status_code == 201
        response = client.post(
            "/api/v1/customer/create", json=new_customer(email="otra@correo.com")
        )
        assert response.status_code == 409
        assert error_code(response) == "limit_reached"

    def test_a_cancelled_card_frees_its_place(
        self, client: TestClient, session: Session, two_businesses, tier
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "free", max_customers=1)
        (customer,) = fill_customers(session, business, tier, 1)
        login(client, ADMIN)
        assert client.post(f"/api/v1/customer/{customer.id}/cancel").status_code == 200
        assert client.post("/api/v1/customer/create", json=new_customer()).status_code == 201

    def test_the_other_business_does_not_count(
        self, client: TestClient, session: Session, two_businesses, tier
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free", max_customers=1)
        tier_b = add_tier(session, two_businesses["business_b"], "Oro", 0)
        fill_customers(session, two_businesses["business_b"], tier_b, 3)
        login(client, ADMIN)
        assert client.post("/api/v1/customer/create", json=new_customer()).status_code == 201

    def test_ended_trial_uses_the_free_limits(
        self, client: TestClient, session: Session, two_businesses, tier
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "business")
        business.trial_ends_at = utc_now() - timedelta(days=1)
        session.add(business)
        session.commit()
        free_limit = plan_service.get_by_key(session, "free").max_customers
        fill_customers(session, business, tier, free_limit)
        login(client, ADMIN)
        response = client.post("/api/v1/customer/create", json=new_customer())
        assert response.status_code == 409
        assert error_code(response) == "limit_reached"

    def test_unlimited_plan(self, client: TestClient, session: Session, two_businesses, tier):
        business = two_businesses["business_a"]
        set_plan(session, business, "chain", max_customers=None)
        fill_customers(session, business, tier, 5)
        login(client, ADMIN)
        assert client.post("/api/v1/customer/create", json=new_customer()).status_code == 201


class TestUserCapacity:
    NEW_USER = {"name": "New Employee", "email": "new@demo.mx", "password": "password123"}

    def test_create_over_the_limit_is_409(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free", max_users=2)
        login(client, ADMIN)
        response = client.post("/api/v1/user/create", json=self.NEW_USER)
        assert response.status_code == 409
        assert error_code(response) == "limit_reached"

    def test_an_inactive_user_does_not_count(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free", max_users=2)
        login(client, ADMIN)
        employee = two_businesses["employee_a"]
        url = f"/api/v1/user/{employee.id}/update"
        assert client.patch(url, json={"is_active": False}).status_code == 200
        assert client.post("/api/v1/user/create", json=self.NEW_USER).status_code == 201

    def test_reactivating_over_the_limit_is_409(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free", max_users=2)
        login(client, ADMIN)
        employee = two_businesses["employee_a"]
        url = f"/api/v1/user/{employee.id}/update"
        client.patch(url, json={"is_active": False})
        assert client.post("/api/v1/user/create", json=self.NEW_USER).status_code == 201
        response = client.patch(url, json={"is_active": True})
        assert response.status_code == 409
        assert error_code(response) == "limit_reached"
        session.expire_all()
        assert session.get(User, employee.id).is_active is False

    def test_editing_an_active_user_is_not_blocked(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        """Already at the limit: changing a name or re-sending is_active=true is fine."""
        set_plan(session, two_businesses["business_a"], "free", max_users=2)
        login(client, ADMIN)
        url = f"/api/v1/user/{two_businesses['employee_a'].id}/update"
        response = client.patch(url, json={"name": "Luis Pérez", "is_active": True})
        assert response.status_code == 200


class TestFeatures:
    def test_images_need_the_plan(
        self, client: TestClient, session: Session, two_businesses, tier, storage
    ) -> None:
        business = two_businesses["business_a"]
        set_plan(session, business, "free")
        (customer,) = fill_customers(session, business, tier, 1)
        login(client, ADMIN)
        png = {"file": ("l.png", make_image(), "image/png")}
        jpg = {"file": ("f.jpg", make_image("JPEG"), "image/jpeg")}
        for response in (
            client.post("/api/v1/logo/update", files=png),
            client.post(f"/api/v1/customer/{customer.id}/photo/update", files=jpg),
            client.post("/api/v1/user/photo/update", files=png),
        ):
            assert response.status_code == 403
            assert error_code(response) == "plan_required"

    def test_images_with_the_plan(
        self, client: TestClient, session: Session, two_businesses, storage
    ) -> None:
        set_plan(session, two_businesses["business_a"], "counter")
        login(client, ADMIN)
        png = {"file": ("l.png", make_image(), "image/png")}
        assert client.post("/api/v1/logo/update", files=png).status_code == 200

    def test_export_needs_the_plan(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free")
        login(client, ADMIN)
        response = client.get("/api/v1/movement/export")
        assert response.status_code == 403
        assert error_code(response) == "plan_required"

    def test_export_with_the_plan(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        set_plan(session, two_businesses["business_a"], "counter")
        login(client, ADMIN)
        assert client.get("/api/v1/movement/export").status_code == 200

    def test_permission_is_checked_before_the_plan(
        self, client: TestClient, session: Session, two_businesses
    ) -> None:
        """An employee sees 403 for the permission, not a plan to upgrade."""
        set_plan(session, two_businesses["business_a"], "free")
        login(client, "employee.a@demo.mx")
        response = client.get("/api/v1/movement/export")
        assert response.status_code == 403
        assert error_code(response) != "plan_required"


class TestHistoryWindow:
    @pytest.fixture
    def purchases(self, client: TestClient, session: Session, two_businesses, tier) -> dict:
        business = two_businesses["business_a"]
        (customer,) = fill_customers(session, business, tier, 1)
        login(client, "employee.a@demo.mx")
        ids = {
            "old": charge(client, session, customer.id, 100_000, 90),
            "new": charge(client, session, customer.id, 20_000, 5),
        }
        login(client, ADMIN)
        return {"customer": customer, **ids}

    def test_free_plan_shows_its_days_only(
        self, client: TestClient, session: Session, two_businesses, purchases
    ) -> None:
        set_plan(session, two_businesses["business_a"], "free", history_days=60)
        body = client.get("/api/v1/movement/list").json()
        assert [item["id"] for item in body["items"]] == [purchases["new"]]

    def test_unlimited_history_shows_everything(
        self, client: TestClient, session: Session, two_businesses, purchases
    ) -> None:
        set_plan(session, two_businesses["business_a"], "business")
        body = client.get("/api/v1/movement/list").json()
        assert {item["id"] for item in body["items"]} == {purchases["old"], purchases["new"]}

    def test_the_window_never_touches_the_balance(
        self, client: TestClient, session: Session, two_businesses, purchases
    ) -> None:
        customer_url = f"/api/v1/customer/{purchases['customer'].id}"
        set_plan(session, two_businesses["business_a"], "business")
        before = client.get(customer_url).json()["points_balance"]
        set_plan(session, two_businesses["business_a"], "free", history_days=60)
        assert client.get(customer_url).json()["points_balance"] == before
        assert before > 0


class TestPlatform:
    def test_the_platform_owner_is_not_limited_by_a_plan(self, two_businesses) -> None:
        checker = require_plan_feature(plan_service.Feature.IMAGES)
        assert checker(session=None, user=two_businesses["platform"]) is None
