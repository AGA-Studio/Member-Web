"""POST /api/v1/registration/create: public business sign-up (issue #69).

Acceptance criteria of the wiki page "Registro de negocios: decisión".
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from core.config import settings
from models import Business, BusinessStatus, Tier, User
from services import plan_service, registration_service
from services.customer_service import as_utc, utc_now
from tests.api.test_customer import add_customer, add_tier
from tests.api.test_turnstile import FAILING_SECRET, PASSING_SECRET, TOKEN, siteverify  # noqa: F401
from tests.conftest import login

URL = "/api/v1/registration/create"


def body(**overrides) -> dict:
    return {
        "business_name": "  Café   Luna ",
        "admin_name": "Ana Torres",
        "email": "Ana@Cafe-Luna.mx",
        "password": "password123",
        **overrides,
    }


def plan_id(session: Session, key: str) -> int:
    plan = plan_service.get_by_key(session, key)
    assert plan is not None
    return plan.id


def counts(session: Session) -> tuple[int, int, int]:
    session.expire_all()
    return tuple(
        session.exec(select(func.count()).select_from(model)).one()
        for model in (Business, User, Tier)
    )


@pytest.fixture
def open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "registration_enabled", True)


@pytest.mark.usefixtures("open_registration")
class TestSignUp:
    def test_creates_business_admin_tiers_and_plan(self, client: TestClient, session) -> None:
        response = client.post(URL, json=body())
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["name"] == "Café Luna"
        assert data["email"] == "ana@cafe-luna.mx"
        assert (data["plan_key"], data["plan"], data["trial_ends_at"]) == ("free", "Gratis", None)

        business = session.get(Business, data["business_id"])
        assert business.status == BusinessStatus.ACTIVE
        assert business.plan_id == plan_id(session, "free")
        tiers = session.exec(select(Tier).where(Tier.business_id == business.id)).all()
        assert sorted(t.name for t in tiers) == ["Básico", "Oro", "Plata"]
        assert all(t.price_cents == 0 and t.points_per_ten == 0 for t in tiers)

    def test_the_admin_logs_in_to_an_empty_panel(self, client: TestClient) -> None:
        client.post(URL, json=body())
        login(client, "ana@cafe-luna.mx")
        me = client.get("/api/v1/auth/me").json()
        assert me["role"] == "admin"
        assert me["business"]["name"] == "Café Luna"
        assert len(client.get("/api/v1/tier/list").json()) == 3
        assert client.get("/api/v1/customer/list").json()["items"] == []

    def test_a_plan_with_trial_starts_it(self, client: TestClient, session) -> None:
        data = client.post(URL, json=body(plan_id=plan_id(session, "business"))).json()
        assert data["plan_key"] == "business"
        ends = as_utc(session.get(Business, data["business_id"]).trial_ends_at)
        assert timedelta(days=29, hours=23) < ends - utc_now() <= timedelta(days=30)

    @pytest.mark.parametrize("key", ["counter", "chain"])
    def test_paid_or_hidden_plan_is_plan_invalid(self, client: TestClient, session, key) -> None:
        before = counts(session)
        response = client.post(URL, json=body(plan_id=plan_id(session, key)))
        assert response.status_code == 422
        assert response.json()["code"] == "plan_invalid"
        assert counts(session) == before

    def test_unknown_plan_is_plan_invalid(self, client: TestClient) -> None:
        response = client.post(URL, json=body(plan_id=999))
        assert (response.status_code, response.json()["code"]) == (422, "plan_invalid")

    def test_taken_email_is_409_and_writes_nothing(
        self, client: TestClient, session, two_businesses
    ) -> None:
        before = counts(session)
        response = client.post(URL, json=body(email="ADMIN.A@demo.mx"))
        assert response.status_code == 409
        assert response.json()["code"] == "email_taken"
        assert counts(session) == before

    def test_two_sign_ups_at_once_never_500(
        self, client: TestClient, session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """H6, reproduced like `TestEmailRace`: without the pre-check only the
        unique index stops the second sign-up, and nothing of it is left behind."""
        assert client.post(URL, json=body(business_name="Uno")).status_code == 201
        before = counts(session)
        monkeypatch.setattr(registration_service, "_ensure_email_available", lambda *_: None)
        response = client.post(URL, json=body(business_name="Dos"))
        assert (response.status_code, response.json()["code"]) == (409, "email_taken")
        assert counts(session) == before

    @pytest.mark.parametrize(
        "field, value",
        [
            ("business_name", "A"),
            ("admin_name", "A"),
            ("email", "no-es-correo"),
            ("password", "corta"),
        ],
    )
    def test_invalid_fields_are_422(self, client: TestClient, field, value) -> None:
        response = client.post(URL, json=body(**{field: value}))
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_the_new_business_sees_no_other_business(
        self, client: TestClient, session, two_businesses
    ) -> None:
        tier = add_tier(session, two_businesses["business_a"], "Oro A", 0)
        other = add_customer(session, two_businesses["business_a"], tier, "Laura", code="MP-AAAA1")
        client.post(URL, json=body())
        login(client, "ana@cafe-luna.mx")
        assert client.get("/api/v1/customer/list").json()["items"] == []
        assert client.get(f"/api/v1/customer/{other.id}").status_code == 404
        names = {t["name"] for t in client.get("/api/v1/tier/list").json()}
        assert "Oro A" not in names


class TestGuards:
    def test_closed_by_default(self, client: TestClient, session) -> None:
        before = counts(session)
        response = client.post(URL, json=body())
        assert (response.status_code, response.json()["code"]) == (403, "registration_closed")
        assert counts(session) == before

    @pytest.mark.usefixtures("open_registration")
    def test_sixth_attempt_per_ip_is_rate_limited(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr(settings, "registration_rate_limit_per_hour", 5)
        for index in range(5):
            client.post(URL, json=body(email=f"user{index}@luna.mx"))
        response = client.post(URL, json=body(email="sixth@luna.mx"))
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"
        assert int(response.headers["Retry-After"]) > 0

    @pytest.mark.usefixtures("open_registration")
    def test_turnstile_is_required_when_on(
        self,
        client: TestClient,
        session,
        monkeypatch,
        siteverify,  # noqa: F811
    ) -> None:
        monkeypatch.setattr(settings, "turnstile_enabled", True)
        monkeypatch.setattr(settings, "turnstile_secret", FAILING_SECRET)
        response = client.post(URL, json=body(), headers={"X-Turnstile-Token": TOKEN})
        assert (response.status_code, response.json()["code"]) == (400, "turnstile_failed")

        monkeypatch.setattr(settings, "turnstile_secret", PASSING_SECRET)
        response = client.post(URL, json=body(), headers={"X-Turnstile-Token": TOKEN})
        assert response.status_code == 201
