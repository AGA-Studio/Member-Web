"""Membership payments and validity months (contract, section 9, DECISIÓN 9)."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Business, MembershipPayment, TierFinish, User
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
