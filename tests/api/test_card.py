"""Digital card delivery: link and public card (contract, section 13)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.config import settings
from models import BusinessStatus, CardDelivery, Customer, TierFinish
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login

CUSTOMER = "/api/v1/customer"
CARD = "/api/v1/card"
NOT_FOUND = {"detail": "Card link not found", "code": "card_link_not_found"}


@pytest.fixture
def cards(session: Session, two_businesses) -> dict:
    """Business A: an active, an expired and a cancelled card. Logged in as admin A."""
    business = two_businesses["business_a"]
    tier = add_tier(session, business, "Oro", 39_900, finish=TierFinish.GOLD)
    return {
        "business": business,
        "tier": tier,
        "active": add_customer(session, business, tier, "Laura Méndez", code="MP-4F7K2"),
        "expired": add_customer(
            session, business, tier, "Ricardo Flores", code="MP-6QXZ9", issued_days_ago=400
        ),
        "cancelled": add_customer(
            session, business, tier, "Daniela Vega", code="MP-4YGK8", cancelled=True
        ),
    }


@pytest.fixture
def admin(client: TestClient, cards) -> TestClient:
    login(client, "admin.a@demo.mx")
    return client


def new_link(client: TestClient, customer: Customer) -> str:
    response = client.post(f"{CUSTOMER}/{customer.id}/card-link")
    assert response.status_code == 200, response.text
    return response.json()["url"].rsplit("/", 1)[1]


def links_of(session: Session, customer: Customer) -> list[CardDelivery]:
    session.expire_all()
    query = select(CardDelivery).where(CardDelivery.customer_id == customer.id)
    return list(session.exec(query).all())


class TestCreateLink:
    def test_returns_the_frontend_url_and_the_card_validity(self, admin, cards) -> None:
        response = admin.post(f"{CUSTOMER}/{cards['active'].id}/card-link")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"url", "expires_at"}
        prefix = f"{settings.frontend_public_url}/tarjeta/"
        assert body["url"].startswith(prefix)
        assert len(body["url"].removeprefix(prefix)) == 43  # token_urlsafe(32)
        valid_until = cards["active"].valid_until.replace(tzinfo=UTC)
        assert datetime.fromisoformat(body["expires_at"]) == valid_until

    def test_stores_only_the_hash_of_the_token(self, admin, cards, session: Session) -> None:
        token = new_link(admin, cards["active"])
        [link] = links_of(session, cards["active"])
        assert link.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps(link.model_dump(mode="json"))

    def test_tokens_are_random(self, admin, cards) -> None:
        tokens = {new_link(admin, cards["active"]) for _ in range(5)}
        assert len(tokens) == 5
        assert not any(cards["active"].code.lower() in token.lower() for token in tokens)

    def test_a_new_link_revokes_the_previous_one(self, admin, cards, session: Session) -> None:
        old = new_link(admin, cards["active"])
        new = new_link(admin, cards["active"])
        assert admin.get(f"{CARD}/{old}").json() == NOT_FOUND
        assert admin.get(f"{CARD}/{new}").status_code == 200
        active = [link for link in links_of(session, cards["active"]) if link.revoked_at is None]
        assert len(active) == 1

    def test_cancelled_card_is_409(self, admin, cards) -> None:
        response = admin.post(f"{CUSTOMER}/{cards['cancelled'].id}/card-link")
        assert response.status_code == 409
        assert response.json()["code"] == "customer_cancelled"

    def test_expired_card_is_409(self, admin, cards) -> None:
        response = admin.post(f"{CUSTOMER}/{cards['expired'].id}/card-link")
        assert response.status_code == 409
        assert response.json()["code"] == "customer_expired"

    def test_unknown_customer_is_404(self, admin) -> None:
        response = admin.post(f"{CUSTOMER}/999999/card-link")
        assert response.status_code == 404
        assert response.json()["code"] == "customer_not_found"


class TestPublicCard:
    def test_has_the_contract_shape(self, admin, cards) -> None:
        token = new_link(admin, cards["active"])
        admin.cookies.clear()
        response = admin.get(f"{CARD}/{token}")
        assert response.status_code == 200
        body = response.json()
        assert datetime.fromisoformat(body.pop("valid_until")) == cards[
            "active"
        ].valid_until.replace(tzinfo=UTC)
        assert body == {
            "business": {"name": "Business A", "logo_url": None},
            "full_name": "Laura Méndez",
            "code": "MP-4F7K2",
            "level": {"name": "Oro", "finish": "gold"},
            "status": "active",
            "wallet": {"google": False},
        }

    def test_never_exposes_private_data(self, admin, cards) -> None:
        token = new_link(admin, cards["active"])
        response = admin.get(f"{CARD}/{token}")
        for secret in ("@correo.com", "email", "phone", "points", "cashback", '"id"'):
            assert secret not in response.text
        body = response.json()
        assert set(body) == {
            "business",
            "full_name",
            "code",
            "level",
            "status",
            "valid_until",
            "wallet",
        }
        assert set(body["business"]) == {"name", "logo_url"}
        assert set(body["level"]) == {"name", "finish"}

    def test_is_never_cached(self, admin, cards) -> None:
        token = new_link(admin, cards["active"])
        assert admin.get(f"{CARD}/{token}").headers["Cache-Control"] == "no-store"
        assert admin.get(f"{CARD}/unknown").headers["Cache-Control"] == "no-store"

    @pytest.mark.parametrize("token", ["unknown", "x" * 43, "x" * 500])
    def test_unknown_token_is_404(self, client: TestClient, token: str) -> None:
        response = client.get(f"{CARD}/{token}")
        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_cancelling_the_card_revokes_the_link(self, admin, cards, session: Session) -> None:
        token = new_link(admin, cards["active"])
        admin.post(f"{CUSTOMER}/{cards['active'].id}/cancel")
        assert admin.get(f"{CARD}/{token}").json() == NOT_FOUND
        assert all(link.revoked_at for link in links_of(session, cards["active"]))

    def test_expired_card_is_the_same_404(self, admin, cards, session: Session) -> None:
        token = new_link(admin, cards["active"])
        customer = session.get(Customer, cards["active"].id)
        customer.valid_until = datetime.now(UTC) - timedelta(days=1)
        session.add(customer)
        session.commit()
        response = admin.get(f"{CARD}/{token}")
        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_renewed_card_opens_again(self, admin, cards, session: Session) -> None:
        token = new_link(admin, cards["active"])
        customer = session.get(Customer, cards["active"].id)
        customer.valid_until = datetime.now(UTC) - timedelta(days=1)
        session.add(customer)
        session.commit()
        customer.valid_until = datetime.now(UTC) + timedelta(days=365)
        session.add(customer)
        session.commit()
        assert admin.get(f"{CARD}/{token}").status_code == 200

    def test_suspended_business_is_the_same_404(self, admin, cards, session: Session) -> None:
        token = new_link(admin, cards["active"])
        business = cards["business"]
        business.status = BusinessStatus.SUSPENDED
        session.add(business)
        session.commit()
        assert admin.get(f"{CARD}/{token}").json() == NOT_FOUND

    def test_too_many_requests_per_ip_is_429(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr(settings, "card_rate_limit_per_minute", 3)
        for _ in range(3):
            assert client.get(f"{CARD}/unknown").status_code == 404
        response = client.get(f"{CARD}/unknown")
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"
        assert int(response.headers["Retry-After"]) >= 1
        assert response.headers["Cache-Control"] == "no-store"


class TestPermissions:
    @pytest.mark.parametrize("action", ["card-link"])
    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    def test_only_the_admin(self, client: TestClient, cards, action: str, email: str) -> None:
        login(client, email)
        assert client.post(f"{CUSTOMER}/{cards['active'].id}/{action}").status_code == 403

    @pytest.mark.parametrize("action", ["card-link"])
    def test_without_session_is_401(self, client: TestClient, cards, action: str) -> None:
        assert client.post(f"{CUSTOMER}/{cards['active'].id}/{action}").status_code == 401

    def test_public_card_needs_no_session(self, admin, cards) -> None:
        token = new_link(admin, cards["active"])
        admin.post("/api/v1/auth/logout")
        admin.cookies.clear()
        assert admin.get(f"{CARD}/{token}").status_code == 200
