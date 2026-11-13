"""scripts/seed.py: demo data for the MVP (two isolated businesses)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.config import settings
from core.security import verify_password
from models import Business, BusinessStatus, CardStatus, Customer, Purchase, Role, Tier, User
from schemas.validators import normalize_person_name
from scripts import seed as seed_module
from scripts.seed import CUSTOMERS, DEMO_PASSWORD, USERS, SeedError, resolve_password, seed
from tests.conftest import login

PASSWORD = "seed-password-123"


def users_by_email(session: Session) -> dict[str, User]:
    return {user.email: user for user in session.exec(select(User)).all()}


class TestSeedData:
    def test_creates_two_active_businesses(self, session: Session) -> None:
        seed(session, PASSWORD)
        businesses = session.exec(select(Business)).all()
        assert {b.name for b in businesses} == {"Café Aurora", "Gimnasio Titán"}
        assert {b.status for b in businesses} == {BusinessStatus.ACTIVE}

    def test_creates_the_demo_users_with_their_roles(self, session: Session) -> None:
        seed(session, PASSWORD)
        users = users_by_email(session)
        assert {email: user.role for email, user in users.items()} == {
            "owner@memberplus.mx": Role.PLATFORM,
            "admin@cafe-aurora.mx": Role.ADMIN,
            "caja@cafe-aurora.mx": Role.EMPLOYEE,
            "admin@gimnasio-titan.mx": Role.ADMIN,
        }

    def test_users_belong_to_the_right_business(self, session: Session) -> None:
        seed(session, PASSWORD)
        users = users_by_email(session)
        aurora = session.exec(select(Business).where(Business.name == "Café Aurora")).one()
        titan = session.exec(select(Business).where(Business.name == "Gimnasio Titán")).one()
        assert users["owner@memberplus.mx"].business_id is None
        assert users["admin@cafe-aurora.mx"].business_id == aurora.id
        assert users["caja@cafe-aurora.mx"].business_id == aurora.id
        assert users["admin@gimnasio-titan.mx"].business_id == titan.id

    def test_passwords_are_hashed(self, session: Session) -> None:
        seed(session, PASSWORD)
        for user in users_by_email(session).values():
            assert user.hashed_password.startswith("$argon2id$")
            assert verify_password(PASSWORD, user.hashed_password)

    @pytest.mark.parametrize(("email", "name", "role", "business"), USERS)
    def test_demo_names_follow_the_name_rule(self, email, name, role, business) -> None:
        # Same rule the API applies (H5), so the demo data is valid data.
        assert normalize_person_name(name) == name


class TestSeedTiers:
    def test_cafe_aurora_gets_the_contract_tiers(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "caja@cafe-aurora.mx", PASSWORD)
        tiers = [
            (
                t["name"],
                t["finish"],
                t["price_cents"],
                t["discount_percent"],
                t["points_per_ten"],
                t["cashback_percent"],
            )
            for t in client.get("/api/v1/tier/list").json()
        ]
        assert tiers == [
            ("Bronce", "bronze", 0, 5, 1, 0),
            ("Plata", "silver", 19_900, 10, 1, 1),
            ("Oro", "gold", 39_900, 15, 1, 3),
            ("Onyx", "onyx", 69_900, 20, 2, 5),
        ]

    def test_gimnasio_titan_gets_different_tiers(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "admin@gimnasio-titan.mx", PASSWORD)
        names = [t["name"] for t in client.get("/api/v1/tier/list").json()]
        assert names == ["Básico", "Premium"]

    def test_a_better_tier_costs_more(self, session: Session) -> None:
        # "Por cobro": more benefits, higher price.
        seed(session, PASSWORD)
        for business in session.exec(select(Business)).all():
            query = select(Tier).where(Tier.business_id == business.id).order_by(Tier.price_cents)
            discounts = [t.discount_percent for t in session.exec(query).all()]
            assert discounts == sorted(discounts)

    def test_an_edited_tier_is_not_overwritten(self, session: Session) -> None:
        seed(session, PASSWORD)
        gold = session.exec(select(Tier).where(Tier.name == "Oro")).one()
        gold.price_cents = 45_000
        session.add(gold)
        session.commit()
        seed(session, PASSWORD)
        session.refresh(gold)
        assert gold.price_cents == 45_000


class TestSeedCustomers:
    def test_cafe_aurora_has_twelve_customers_in_every_state(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "admin@cafe-aurora.mx", PASSWORD)
        assert client.get("/api/v1/customer/summary").json() == {
            "all": 12,
            "active": 10,
            "expiring": 2,
            "expired": 1,
            "cancelled": 1,
        }

    def test_gimnasio_titan_has_its_own_customers(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "admin@gimnasio-titan.mx", PASSWORD)
        names = [c["full_name"] for c in client.get("/api/v1/customer/list").json()["items"]]
        assert names == ["Paola Cruz", "Roberto Díaz"]

    def test_the_contract_card_is_found_at_the_counter(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "caja@cafe-aurora.mx", PASSWORD)
        card = client.get("/api/v1/customer/lookup", params={"code": "mp-4f7k2"}).json()
        assert (card["full_name"], card["level"]["name"]) == ("Laura Méndez", "Oro")

    def test_tiers_count_the_seeded_customers(self, session: Session, client: TestClient) -> None:
        seed(session, PASSWORD)
        login(client, "admin@cafe-aurora.mx", PASSWORD)
        counts = {t["name"]: t["customers_count"] for t in client.get("/api/v1/tier/list").json()}
        # Daniela Vega (Plata) is cancelled and does not count.
        assert counts == {"Bronce": 4, "Plata": 2, "Oro": 3, "Onyx": 2}

    @pytest.mark.parametrize("row", CUSTOMERS, ids=[row[1] for row in CUSTOMERS])
    def test_demo_customers_follow_the_rules(self, row) -> None:
        _, code, name, *_ = row
        assert normalize_person_name(name) == name
        assert code[3:].isalnum() and not set(code[3:]) & set("01OIL")


class TestSeedPurchases:
    def test_balances_follow_the_checkout_formula(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "caja@cafe-aurora.mx", PASSWORD)
        laura = client.get("/api/v1/customer/lookup", params={"code": "MP-4F7K2"}).json()
        # $1,000 in Oro = 85 points and $25.50; then $250 spending that cashback = 21 and $6.38.
        assert (laura["points_balance"], laura["cashback_balance_cents"]) == (106, 638)
        assert laura["last_purchase_at"] is not None

    def test_purchase_after_expiry_earned_nothing(self, session: Session) -> None:
        seed(session, PASSWORD)
        ricardo = session.exec(select(Customer).where(Customer.code == "MP-6QXZ9")).one()
        purchases = session.exec(
            select(Purchase).where(Purchase.customer_id == ricardo.id).order_by(Purchase.id)
        ).all()
        assert [p.card_status for p in purchases] == [CardStatus.ACTIVE, CardStatus.EXPIRED]
        assert (purchases[1].points_earned, purchases[1].total_cents) == (0, 9_000)

    def test_gimnasio_titan_has_its_own_purchase(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "admin@gimnasio-titan.mx", PASSWORD)
        roberto = client.get("/api/v1/customer/lookup", params={"code": "MP-3GYM4"}).json()
        assert (roberto["points_balance"], roberto["cashback_balance_cents"]) == (106, 1_078)


class TestIdempotency:
    def test_second_run_creates_nothing(self, session: Session) -> None:
        first = seed(session, PASSWORD)
        second = seed(session, PASSWORD)
        assert len(first.created) == 39
        assert second.created == []
        assert len(second.existing) == 39
        assert len(session.exec(select(Business)).all()) == 2
        assert len(session.exec(select(User)).all()) == 4
        assert len(session.exec(select(Tier)).all()) == 6
        assert len(session.exec(select(Customer)).all()) == 14
        assert len(session.exec(select(Purchase)).all()) == 13

    def test_existing_password_is_never_changed(self, session: Session) -> None:
        seed(session, PASSWORD)
        seed(session, "another-password-456")
        admin = users_by_email(session)["admin@cafe-aurora.mx"]
        assert verify_password(PASSWORD, admin.hashed_password)

    def test_completes_partial_data(self, session: Session) -> None:
        session.add(Business(name="Café Aurora", status=BusinessStatus.ACTIVE))
        session.commit()
        result = seed(session, PASSWORD)
        assert result.existing == ["business  Café Aurora"]
        assert len(session.exec(select(Business)).all()) == 2


class TestDemoScenario:
    """The MVP demo script runs on top of this data."""

    def test_admin_a_sees_only_cafe_aurora(self, session: Session, client: TestClient) -> None:
        seed(session, PASSWORD)
        login(client, "admin@cafe-aurora.mx", PASSWORD)
        emails = {u["email"] for u in client.get("/api/v1/user/list").json()}
        assert emails == {"admin@cafe-aurora.mx", "caja@cafe-aurora.mx"}

    def test_admin_b_sees_nothing_of_a(self, session: Session, client: TestClient) -> None:
        seed(session, PASSWORD)
        login(client, "admin@gimnasio-titan.mx", PASSWORD)
        emails = {u["email"] for u in client.get("/api/v1/user/list").json()}
        assert emails == {"admin@gimnasio-titan.mx"}

    def test_every_demo_user_can_log_in(self, session: Session, client: TestClient) -> None:
        seed(session, PASSWORD)
        for email, _, role, _ in USERS:
            client.cookies.clear()
            login(client, email, PASSWORD)
            assert client.get("/api/v1/auth/me").json()["role"] == role


class TestPassword:
    def test_development_uses_the_demo_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "seed_password", "")
        monkeypatch.setattr(settings, "environment", "development")
        assert resolve_password() == DEMO_PASSWORD

    def test_seed_password_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "seed_password", PASSWORD)
        monkeypatch.setattr(settings, "environment", "production")
        assert resolve_password() == PASSWORD

    def test_production_requires_seed_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "seed_password", "")
        monkeypatch.setattr(settings, "environment", "production")
        with pytest.raises(SeedError, match="required"):
            resolve_password()

    def test_short_seed_password_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "seed_password", "short")
        with pytest.raises(SeedError, match="at least 8"):
            resolve_password()


class TestCommandLine:
    def test_main_seeds_and_prints(
        self, session: Session, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr(settings, "seed_password", "")
        monkeypatch.setattr(settings, "environment", "development")
        assert seed_module.main() == 0
        out = capsys.readouterr().out
        assert "created   business  Café Aurora" in out
        assert f"Demo password for the new users: {DEMO_PASSWORD}" in out

    def test_main_reports_existing_data(
        self, session: Session, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr(settings, "seed_password", PASSWORD)
        seed_module.main()
        capsys.readouterr()
        assert seed_module.main() == 0
        out = capsys.readouterr().out
        assert "exists    user      admin@cafe-aurora.mx" in out
        assert "created" not in out

    def test_main_never_prints_a_custom_password(
        self, session: Session, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr(settings, "seed_password", PASSWORD)
        assert seed_module.main() == 0
        assert PASSWORD not in capsys.readouterr().out

    def test_main_fails_without_password_in_production(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr(settings, "seed_password", "")
        monkeypatch.setattr(settings, "environment", "production")
        assert seed_module.main() == 1
        assert "Seed aborted" in capsys.readouterr().err
