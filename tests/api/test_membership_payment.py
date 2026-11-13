"""Membership payments and validity months (contract, section 9, DECISIÓN 9)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Business, Customer, MembershipPayment, TierFinish, User
from services.customer_service import add_months
from tests.api.test_customer import add_tier
from tests.conftest import login

CUSTOMER = "/api/v1/customer"


@pytest.fixture
def tiers(session: Session, two_businesses) -> dict:
    business = two_businesses["business_a"]
    return {
        "free": add_tier(session, business, "Básico", 0),
        "gold": add_tier(session, business, "Oro", 39_900, finish=TierFinish.GOLD),
    }


@pytest.fixture
def admin(client: TestClient, tiers) -> TestClient:
    login(client, "admin.a@demo.mx")
    return client


def create(client: TestClient, **extra):
    body = {
        "full_name": "Sofía Hernández",
        "email": "sofia@correo.com",
        "send_card_email": False,
        **extra,
    }
    return client.post(f"{CUSTOMER}/create", json=body)


def payments(session: Session) -> list[MembershipPayment]:
    session.expire_all()
    return list(session.exec(select(MembershipPayment)).all())


def as_datetime(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


class TestFirstPayment:
    def test_records_the_tier_price(self, admin, tiers, session: Session) -> None:
        response = create(admin, level_id=tiers["gold"].id)
        assert response.status_code == 201
        [payment] = payments(session)
        body = response.json()
        admin_a = session.exec(select(User).where(User.email == "admin.a@demo.mx")).one()
        assert payment.customer_id == body["id"]
        assert payment.business_id == tiers["gold"].business_id
        assert (payment.kind, payment.method) == ("new", "cash")
        assert payment.amount_cents == 39_900
        assert (payment.tier_id, payment.tier_name) == (tiers["gold"].id, "Oro")
        assert payment.recorded_by == admin_a.id
        assert payment.period_start.replace(tzinfo=UTC) == as_datetime(body["issued_at"])
        assert payment.period_end.replace(tzinfo=UTC) == as_datetime(body["valid_until"])

    def test_the_admin_can_change_amount_and_method(self, admin, tiers, session) -> None:
        create(admin, level_id=tiers["gold"].id, amount_cents=30_000, payment_method="transfer")
        [payment] = payments(session)
        assert (payment.amount_cents, payment.method) == (30_000, "transfer")

    def test_free_tier_records_no_payment(self, admin, tiers, session: Session) -> None:
        assert create(admin, level_id=tiers["free"].id).status_code == 201
        assert payments(session) == []

    def test_amount_zero_records_no_payment(self, admin, tiers, session: Session) -> None:
        assert create(admin, level_id=tiers["gold"].id, amount_cents=0).status_code == 201
        assert payments(session) == []

    @pytest.mark.parametrize("amount", [-1, 100_000_001])
    def test_amount_out_of_range_is_422(self, admin, tiers, session, amount: int) -> None:
        response = create(admin, level_id=tiers["gold"].id, amount_cents=amount)
        assert response.status_code == 422
        assert response.json()["code"] == "amount_invalid"
        assert admin.get(f"{CUSTOMER}/list").json()["total"] == 0

    def test_unknown_method_is_422(self, admin, tiers) -> None:
        response = create(admin, level_id=tiers["gold"].id, payment_method="bitcoin")
        assert response.status_code == 422

    def test_duplicate_email_saves_no_payment(self, admin, tiers, session: Session) -> None:
        create(admin, level_id=tiers["gold"].id)
        assert create(admin, level_id=tiers["gold"].id).status_code == 409
        assert len(payments(session)) == 1


class TestValidityMonths:
    def test_default_is_twelve_months(self, admin, tiers) -> None:
        body = create(admin).json()
        issued = as_datetime(body["issued_at"])
        assert as_datetime(body["valid_until"]) == add_months(issued, 12)

    def test_comes_from_the_business(self, admin, tiers, session: Session) -> None:
        business = session.get(Business, tiers["gold"].business_id)
        business.validity_months = 6
        session.add(business)
        session.commit()
        body = create(admin, level_id=tiers["gold"].id).json()
        issued = as_datetime(body["issued_at"])
        assert as_datetime(body["valid_until"]) == add_months(issued, 6)
        [payment] = payments(session)
        assert payment.period_end.replace(tzinfo=UTC) == add_months(issued, 6)


def renew(client: TestClient, customer_id: int, **body):
    return client.post(f"{CUSTOMER}/{customer_id}/renew", json=body)


def set_valid_until(session: Session, customer_id: int, moment: datetime) -> None:
    customer = session.get(Customer, customer_id)
    customer.valid_until = moment
    session.add(customer)
    session.commit()


class TestRenew:
    def test_active_card_renews_from_its_end(self, admin, tiers, session: Session) -> None:
        body = create(admin, level_id=tiers["gold"].id).json()
        old_end = as_datetime(body["valid_until"])
        response = renew(admin, body["id"])
        assert response.status_code == 200
        assert as_datetime(response.json()["valid_until"]) == add_months(old_end, 12)
        renewal = [p for p in payments(session) if p.kind == "renewal"]
        assert len(renewal) == 1
        assert renewal[0].amount_cents == 39_900
        assert renewal[0].period_start.replace(tzinfo=UTC) == old_end
        assert renewal[0].period_end.replace(tzinfo=UTC) == add_months(old_end, 12)

    def test_expired_card_renews_from_now(self, admin, tiers, session: Session) -> None:
        customer_id = create(admin, level_id=tiers["gold"].id).json()["id"]
        set_valid_until(session, customer_id, datetime.now(UTC) - timedelta(days=30))
        before = datetime.now(UTC)
        body = renew(admin, customer_id).json()
        assert body["status"] == "active"
        new_end = as_datetime(body["valid_until"])
        assert add_months(before, 12) <= new_end <= add_months(datetime.now(UTC), 12)

    def test_can_change_tier_amount_and_method(self, admin, tiers, session: Session) -> None:
        customer_id = create(admin, level_id=tiers["free"].id).json()["id"]
        body = renew(
            admin,
            customer_id,
            level_id=tiers["gold"].id,
            amount_cents=35_000,
            payment_method="card",
        ).json()
        assert body["level"]["id"] == tiers["gold"].id
        [payment] = payments(session)
        assert (payment.kind, payment.method, payment.amount_cents) == ("renewal", "card", 35_000)
        assert payment.tier_name == "Oro"

    def test_free_renewal_records_no_payment(self, admin, tiers, session: Session) -> None:
        customer_id = create(admin, level_id=tiers["free"].id).json()["id"]
        assert renew(admin, customer_id).status_code == 200
        assert payments(session) == []

    def test_cancelled_card_is_409(self, admin, tiers, session: Session) -> None:
        body = create(admin, level_id=tiers["gold"].id).json()
        admin.post(f"{CUSTOMER}/{body['id']}/cancel")
        response = renew(admin, body["id"])
        assert response.status_code == 409
        assert response.json()["code"] == "customer_cancelled"
        assert len(payments(session)) == 1
        assert session.get(Customer, body["id"]).valid_until.replace(tzinfo=UTC) == as_datetime(
            body["valid_until"]
        )

    def test_unknown_tier_is_422(self, admin, tiers) -> None:
        customer_id = create(admin, level_id=tiers["gold"].id).json()["id"]
        assert renew(admin, customer_id, level_id=999_999).status_code == 422

    def test_amount_out_of_range_is_422(self, admin, tiers) -> None:
        customer_id = create(admin, level_id=tiers["gold"].id).json()["id"]
        response = renew(admin, customer_id, amount_cents=-5)
        assert response.json()["code"] == "amount_invalid"

    def test_missing_customer_is_404(self, admin, tiers) -> None:
        assert renew(admin, 999_999).status_code == 404

    def test_employee_cannot_renew(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        customer_id = create(client, level_id=tiers["gold"].id).json()["id"]
        login(client, "employee.a@demo.mx")
        assert renew(client, customer_id).status_code == 403


class TestPaymentList:
    def test_most_recent_first(self, admin, tiers, session: Session) -> None:
        customer_id = create(admin, level_id=tiers["gold"].id).json()["id"]
        renew(admin, customer_id, payment_method="transfer")
        body = admin.get(f"{CUSTOMER}/{customer_id}/payment/list").json()
        admin_a = session.exec(select(User).where(User.email == "admin.a@demo.mx")).one()
        assert body["total"] == 2
        assert [p["kind"] for p in body["items"]] == ["renewal", "new"]
        first = body["items"][0]
        assert first["method"] == "transfer"
        assert first["amount_cents"] == 39_900
        assert first["level"] == {"id": tiers["gold"].id, "name": "Oro"}
        assert first["recorded_by_name"] == admin_a.name
        assert as_datetime(first["period_end"]) > as_datetime(first["period_start"])

    def test_keeps_the_tier_name_it_was_paid_with(self, admin, tiers, session) -> None:
        customer_id = create(admin, level_id=tiers["gold"].id).json()["id"]
        gold = tiers["gold"]
        gold.name = "Oro Plus"
        session.add(gold)
        session.commit()
        [item] = admin.get(f"{CUSTOMER}/{customer_id}/payment/list").json()["items"]
        assert item["level"]["name"] == "Oro"

    def test_paginates(self, admin, tiers) -> None:
        customer_id = create(admin, level_id=tiers["gold"].id).json()["id"]
        renew(admin, customer_id)
        renew(admin, customer_id)
        url = f"{CUSTOMER}/{customer_id}/payment/list"
        body = admin.get(url, params={"page_size": 2, "page": 2}).json()
        assert (body["total"], len(body["items"]), body["page"]) == (3, 1, 2)

    def test_empty_for_a_free_customer(self, admin, tiers) -> None:
        customer_id = create(admin, level_id=tiers["free"].id).json()["id"]
        body = admin.get(f"{CUSTOMER}/{customer_id}/payment/list").json()
        assert (body["total"], body["items"]) == (0, [])

    def test_missing_customer_is_404(self, admin, tiers) -> None:
        assert admin.get(f"{CUSTOMER}/999999/payment/list").status_code == 404

    def test_employee_cannot_list(self, client: TestClient, tiers) -> None:
        login(client, "admin.a@demo.mx")
        customer_id = create(client, level_id=tiers["gold"].id).json()["id"]
        login(client, "employee.a@demo.mx")
        assert client.get(f"{CUSTOMER}/{customer_id}/payment/list").status_code == 403
