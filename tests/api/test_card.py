"""Digital card delivery: link, email, public card and Google Wallet (contract, section 13)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.config import settings
from models import BusinessStatus, CardDelivery, CardEmail, Customer, TierFinish
from services import email_service, wallet_service
from tests.api.test_customer import add_customer, add_tier
from tests.conftest import login
from tests.smtp_server import SmtpServer

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


def text_of(message) -> str:
    return message.get_body(("plain",)).get_content()


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


class TestSendLink:
    URL = CUSTOMER + "/{id}/card-link/send"

    def send(self, client: TestClient, customer: Customer):
        return client.post(self.URL.format(id=customer.id))

    def test_emails_the_customer(self, admin, cards) -> None:
        response = self.send(admin, cards["active"])
        assert response.status_code == 200
        body = response.json()
        assert body["sent_to"] == "mp-4f7k2@correo.com"
        assert body["last_sent_at"].endswith(("Z", "+00:00"))
        [message] = email_service.OUTBOX
        assert message["To"] == "mp-4f7k2@correo.com"
        assert message["Subject"] == "Tu tarjeta de Business A"
        assert message["From"] == f"Business A <{settings.mail_from}>"

    def test_email_body_follows_the_contract(self, admin, cards) -> None:
        self.send(admin, cards["active"])
        [message] = email_service.OUTBOX
        text = text_of(message)
        assert text.startswith("Hola, Laura Méndez:")
        assert "Business A te dio una tarjeta de membresía." in text
        assert f"{settings.frontend_public_url}/tarjeta/" in text
        assert "Si no esperabas este correo, puedes ignorarlo." in text
        html = message.get_body(("html",)).get_content().removeprefix("<!doctype html>")
        assert "Ver mi tarjeta" in html
        for secret in ("MP-4F7K2", "puntos", "cashback", "saldo", "!", "¡"):
            assert secret not in text
            assert secret not in html

    def test_the_emailed_link_opens_the_card(self, admin, cards) -> None:
        self.send(admin, cards["active"])
        token = text_of(email_service.OUTBOX[0]).split("/tarjeta/")[1].split()[0]
        assert admin.get(f"{CARD}/{token}").json()["code"] == "MP-4F7K2"

    def test_every_email_carries_a_new_link(self, admin, cards, session: Session) -> None:
        copied = new_link(admin, cards["active"])
        self.send(admin, cards["active"])
        assert admin.get(f"{CARD}/{copied}").json() == NOT_FOUND
        [active] = [link for link in links_of(session, cards["active"]) if not link.revoked_at]
        assert active.last_sent_at is not None

    def test_again_within_a_minute_is_429(self, admin, cards) -> None:
        assert self.send(admin, cards["active"]).status_code == 200
        response = self.send(admin, cards["active"])
        assert response.status_code == 429
        assert response.json()["code"] == "card_email_rate_limited"
        assert 1 <= int(response.headers["Retry-After"]) <= 60
        assert len(email_service.OUTBOX) == 1

    def test_a_rejected_send_keeps_the_link(self, admin, cards) -> None:
        self.send(admin, cards["active"])
        token = text_of(email_service.OUTBOX[0]).split("/tarjeta/")[1].split()[0]
        self.send(admin, cards["active"])
        assert admin.get(f"{CARD}/{token}").status_code == 200

    def add_sends(self, session: Session, customer: Customer, *minutes_ago: int) -> None:
        now = datetime.now(UTC)
        for minutes in minutes_ago:
            session.add(
                CardEmail(
                    business_id=customer.business_id,
                    customer_id=customer.id,
                    sent_at=now - timedelta(minutes=minutes),
                )
            )
        session.commit()

    def test_five_in_an_hour_is_429(self, admin, cards, session: Session) -> None:
        self.add_sends(session, cards["active"], 50, 40, 30, 20, 10)
        response = self.send(admin, cards["active"])
        assert response.status_code == 429
        # The oldest send leaves the window in about 10 minutes.
        assert 540 <= int(response.headers["Retry-After"]) <= 600

    def test_four_in_an_hour_is_fine(self, admin, cards, session: Session) -> None:
        self.add_sends(session, cards["active"], 50, 40, 30, 20)
        assert self.send(admin, cards["active"]).status_code == 200

    def test_sends_older_than_an_hour_do_not_count(self, admin, cards, session) -> None:
        self.add_sends(session, cards["active"], 300, 200, 120, 90, 61)
        assert self.send(admin, cards["active"]).status_code == 200

    def test_cancelled_card_is_409(self, admin, cards) -> None:
        response = self.send(admin, cards["cancelled"])
        assert response.status_code == 409
        assert response.json()["code"] == "customer_cancelled"
        assert not email_service.OUTBOX

    def test_expired_card_is_409(self, admin, cards) -> None:
        assert self.send(admin, cards["expired"]).json()["code"] == "customer_expired"

    def test_unknown_customer_is_404(self, admin) -> None:
        response = admin.post(self.URL.format(id=999999))
        assert response.json()["code"] == "customer_not_found"


class TestSmtp:
    URL = CUSTOMER + "/{id}/card-link/send"

    def use_server(self, monkeypatch, server: SmtpServer) -> None:
        monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
        monkeypatch.setattr(settings, "smtp_port", server.port)
        monkeypatch.setattr(settings, "smtp_tls", "none")
        monkeypatch.setattr(settings, "smtp_timeout_seconds", 5)

    def test_sends_through_the_smtp_server(self, admin, cards, monkeypatch) -> None:
        with SmtpServer() as server:
            self.use_server(monkeypatch, server)
            response = admin.post(self.URL.format(id=cards["active"].id))
        assert response.status_code == 200
        [raw] = server.messages
        assert b"Subject: Tu tarjeta de Business A" in raw
        assert not email_service.OUTBOX

    def test_provider_failure_is_502(self, admin, cards, monkeypatch) -> None:
        with SmtpServer(mode="reject") as server:
            self.use_server(monkeypatch, server)
            response = admin.post(self.URL.format(id=cards["active"].id))
        assert response.status_code == 502
        assert response.json()["code"] == "email_failed"

    def test_production_without_provider_is_502(self, admin, cards, monkeypatch) -> None:
        monkeypatch.setattr(settings, "environment", "production")
        response = admin.post(self.URL.format(id=cards["active"].id))
        assert response.json()["code"] == "email_failed"
        assert not email_service.OUTBOX


class TestCreateCustomer:
    def create(self, client: TestClient, **extra):
        body = {"full_name": "Sofía Hernández", "email": "sofia@correo.com", **extra}
        return client.post(f"{CUSTOMER}/create", json=body)

    def test_sends_the_card_by_default(self, admin, cards) -> None:
        response = self.create(admin)
        assert response.status_code == 201
        assert response.json()["card_email"] == {"status": "sent"}
        [message] = email_service.OUTBOX
        assert message["To"] == "sofia@correo.com"
        token = text_of(message).split("/tarjeta/")[1].split()[0]
        assert admin.get(f"{CARD}/{token}").json()["full_name"] == "Sofía Hernández"

    def test_can_skip_the_email(self, admin, cards, session: Session) -> None:
        response = self.create(admin, send_card_email=False)
        assert response.json()["card_email"] == {"status": "skipped"}
        assert not email_service.OUTBOX
        assert not session.exec(select(CardDelivery)).all()

    def test_a_failed_email_does_not_fail_the_creation(
        self, admin, cards, session: Session, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "environment", "production")
        response = self.create(admin)
        assert response.status_code == 201
        assert response.json()["card_email"] == {"status": "failed"}
        assert session.get(Customer, response.json()["id"]) is not None

    def test_a_slow_provider_is_pending(self, admin, cards, monkeypatch) -> None:
        with SmtpServer(mode="slow", delay=email_service.SEND_DEADLINE_SECONDS + 0.5) as server:
            TestSmtp().use_server(monkeypatch, server)
            started = datetime.now(UTC)
            response = self.create(admin)
            elapsed = datetime.now(UTC) - started
        assert response.status_code == 201
        assert response.json()["card_email"] == {"status": "pending"}
        assert elapsed < timedelta(seconds=email_service.SEND_DEADLINE_SECONDS + 1)

    def test_counts_for_the_email_limit(self, admin, cards) -> None:
        customer_id = self.create(admin).json()["id"]
        response = admin.post(f"{CUSTOMER}/{customer_id}/card-link/send")
        assert response.json()["code"] == "card_email_rate_limited"


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


@pytest.fixture
def wallet_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def wallet(monkeypatch, wallet_key) -> rsa.RSAPublicKey:
    """Google Wallet configured with a test key (never a real one)."""
    pem = wallet_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    account = {"client_email": "wallet@test.iam.gserviceaccount.com", "private_key": pem}
    monkeypatch.setattr(settings, "google_wallet_issuer_id", "3388000000012345678")
    monkeypatch.setattr(settings, "google_wallet_service_account_json", json.dumps(account))
    monkeypatch.setattr(settings, "google_wallet_origins", ["http://localhost:3000"])
    monkeypatch.setattr(settings, "google_wallet_logo_url", "https://memberplus.mx/logo.png")
    return wallet_key.public_key()


def decode_save_url(save_url: str, public_key) -> dict:
    assert save_url.startswith("https://pay.google.com/gp/v/save/")
    token = save_url.removeprefix("https://pay.google.com/gp/v/save/")
    return jwt.decode(token, public_key, algorithms=["RS256"], audience="google")


class TestGoogleWallet:
    def url(self, token: str) -> str:
        return f"{CARD}/{token}/google-wallet"

    def test_without_configuration_is_503(self, admin, cards) -> None:
        token = new_link(admin, cards["active"])
        response = admin.get(self.url(token))
        assert response.status_code == 503
        assert response.json()["code"] == "wallet_unavailable"
        assert response.headers["Cache-Control"] == "no-store"

    def test_unknown_token_is_404_before_503(self, client: TestClient) -> None:
        response = client.get(self.url("unknown"))
        assert (response.status_code, response.json()) == (404, NOT_FOUND)

    def test_cancelled_card_is_404(self, admin, cards, wallet) -> None:
        token = new_link(admin, cards["active"])
        admin.post(f"{CUSTOMER}/{cards['active'].id}/cancel")
        assert admin.get(self.url(token)).json() == NOT_FOUND

    def test_card_says_when_wallet_is_available(self, admin, cards, wallet) -> None:
        token = new_link(admin, cards["active"])
        assert admin.get(f"{CARD}/{token}").json()["wallet"] == {"google": True}

    def test_jwt_is_signed_with_the_service_account(self, admin, cards, wallet) -> None:
        token = new_link(admin, cards["active"])
        response = admin.get(self.url(token))
        assert response.status_code == 200
        assert set(response.json()) == {"save_url"}
        claims = decode_save_url(response.json()["save_url"], wallet)
        assert claims["iss"] == "wallet@test.iam.gserviceaccount.com"
        assert claims["aud"] == "google"
        assert claims["typ"] == "savetowallet"
        assert claims["origins"] == ["http://localhost:3000"]

    def test_jwt_carries_the_class_and_the_object(self, admin, cards, wallet) -> None:
        token = new_link(admin, cards["active"])
        claims = decode_save_url(admin.get(self.url(token)).json()["save_url"], wallet)
        business, customer = cards["business"], cards["active"]
        [loyalty_class] = claims["payload"]["loyaltyClasses"]
        [loyalty_object] = claims["payload"]["loyaltyObjects"]
        assert loyalty_class["id"] == f"3388000000012345678.business_{business.id}"
        assert loyalty_class["programName"] == "Business A"
        assert loyalty_class["issuerName"] == "Member+"
        assert loyalty_class["programLogo"]["sourceUri"]["uri"] == "https://memberplus.mx/logo.png"
        assert loyalty_object["id"] == f"3388000000012345678.customer_{customer.id}"
        assert loyalty_object["classId"] == loyalty_class["id"]
        assert loyalty_object["state"] == "ACTIVE"
        assert loyalty_object["accountName"] == "Laura Méndez"
        assert loyalty_object["accountId"] == "MP-4F7K2"
        assert loyalty_object["barcode"]["type"] == "QR_CODE"
        assert loyalty_object["barcode"]["value"] == "MP-4F7K2"
        assert loyalty_object["textModulesData"][0]["body"] == "Oro"
        assert loyalty_object["validTimeInterval"]["end"]["date"].endswith("Z")

    def test_uses_the_business_logo_when_it_is_https(
        self, admin, cards, wallet, session: Session
    ) -> None:
        business = cards["business"]
        business.logo_url = "https://cdn.example.com/aurora.png"
        session.add(business)
        session.commit()
        token = new_link(admin, cards["active"])
        claims = decode_save_url(admin.get(self.url(token)).json()["save_url"], wallet)
        logo = claims["payload"]["loyaltyClasses"][0]["programLogo"]["sourceUri"]["uri"]
        assert logo == "https://cdn.example.com/aurora.png"

    @pytest.mark.parametrize(
        "account", ["", "not json", "[]", '{"client_email": "a@b.c"}', '{"private_key": "k"}']
    )
    def test_a_broken_service_account_is_not_configured(
        self, wallet, monkeypatch, account: str
    ) -> None:
        monkeypatch.setattr(settings, "google_wallet_service_account_json", account)
        assert wallet_service.is_configured() is False

    @pytest.mark.parametrize("missing", ["google_wallet_issuer_id", "google_wallet_logo_url"])
    def test_every_variable_is_needed(self, wallet, monkeypatch, missing: str) -> None:
        assert wallet_service.is_configured() is True
        monkeypatch.setattr(settings, missing, "")
        assert wallet_service.is_configured() is False


class TestPermissions:
    @pytest.mark.parametrize("action", ["card-link", "card-link/send"])
    @pytest.mark.parametrize("email", ["employee.a@demo.mx", "owner@memberplus.mx"])
    def test_only_the_admin(self, client: TestClient, cards, action: str, email: str) -> None:
        login(client, email)
        assert client.post(f"{CUSTOMER}/{cards['active'].id}/{action}").status_code == 403

    @pytest.mark.parametrize("action", ["card-link", "card-link/send"])
    def test_without_session_is_401(self, client: TestClient, cards, action: str) -> None:
        assert client.post(f"{CUSTOMER}/{cards['active'].id}/{action}").status_code == 401

    def test_public_card_needs_no_session(self, admin, cards) -> None:
        token = new_link(admin, cards["active"])
        admin.post("/api/v1/auth/logout")
        admin.cookies.clear()
        assert admin.get(f"{CARD}/{token}").status_code == 200
