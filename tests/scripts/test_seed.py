"""scripts/seed.py: demo data for the MVP (two isolated businesses)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.config import settings
from core.security import verify_password
from models import Business, BusinessStatus, Role, Tier, User
from schemas.validators import normalize_person_name
from scripts import seed as seed_module
from scripts.seed import DEMO_PASSWORD, USERS, SeedError, resolve_password, seed
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
                t["min_points"],
                t["discount_percent"],
                t["points_per_ten"],
                t["cashback_percent"],
            )
            for t in client.get("/api/v1/tier/list").json()
        ]
        assert tiers == [
            ("Bronce", "bronze", 0, 5, 1, 0),
            ("Plata", "silver", 400, 10, 1, 1),
            ("Oro", "gold", 1000, 15, 1, 3),
            ("Onyx", "onyx", 1500, 20, 2, 5),
        ]

    def test_gimnasio_titan_gets_different_tiers(
        self, session: Session, client: TestClient
    ) -> None:
        seed(session, PASSWORD)
        login(client, "admin@gimnasio-titan.mx", PASSWORD)
        names = [t["name"] for t in client.get("/api/v1/tier/list").json()]
        assert names == ["Básico", "Premium"]

    def test_every_business_has_a_tier_at_zero_points(self, session: Session) -> None:
        seed(session, PASSWORD)
        for business in session.exec(select(Business)).all():
            tiers = session.exec(select(Tier).where(Tier.business_id == business.id)).all()
            assert min(t.min_points for t in tiers) == 0

    def test_an_edited_tier_is_not_overwritten(self, session: Session) -> None:
        seed(session, PASSWORD)
        gold = session.exec(select(Tier).where(Tier.name == "Oro")).one()
        gold.min_points = 1200
        session.add(gold)
        session.commit()
        seed(session, PASSWORD)
        session.refresh(gold)
        assert gold.min_points == 1200


class TestIdempotency:
    def test_second_run_creates_nothing(self, session: Session) -> None:
        first = seed(session, PASSWORD)
        second = seed(session, PASSWORD)
        assert len(first.created) == 12
        assert second.created == []
        assert len(second.existing) == 12
        assert len(session.exec(select(Business)).all()) == 2
        assert len(session.exec(select(User)).all()) == 4
        assert len(session.exec(select(Tier)).all()) == 6

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
