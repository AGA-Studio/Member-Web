"""scripts/simulate.py: demo history in bulk and the scheduled tick."""

import random
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from core.security import hash_password
from models import (
    Business,
    CardStatus,
    Customer,
    MembershipPayment,
    Purchase,
    Role,
    Tier,
    TierFinish,
    User,
)
from schemas.validators import normalize_person_name
from scripts.seed import SOL_CUSTOMERS_COUNT, seed
from scripts.simulate import (
    CASHIER_EMAILS,
    DEMO_BUSINESSES,
    SimulateError,
    bulk,
    charge,
    extra_code,
    history,
    load_businesses,
    main,
    tick,
)
from services.customer_service import as_utc, balance_of

PASSWORD = "seed-password-123"
# Fixed "today": the seed reads the real clock, so the assertions below are
# written against a moment safely inside every card window of the seed data.
NOW = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)


def minimal_businesses(
    session: Session, *, with_tiers: bool = True, with_admin: bool = True
) -> None:
    """Bare businesses for the guard tests: no seed, no customers.

    One user per demo business covers both lookups (in the seed, Titán's
    cashier IS its admin and Sol's is its employee); `with_admin=False` leaves
    only employees, which is what the admin guard needs to fail.
    """
    hashed = hash_password("guard-password-123")
    for key, name in DEMO_BUSINESSES:
        business = Business(name=name)
        session.add(business)
        session.flush()
        if with_tiers:
            session.add(Tier(business_id=business.id, name="Base", finish=TierFinish.SILVER))
        session.add(
            User(
                business_id=business.id,
                name="Admin Uno" if with_admin else "Cajero Uno",
                email=CASHIER_EMAILS[key],
                hashed_password=hashed,
                role=Role.ADMIN if with_admin else Role.EMPLOYEE,
            )
        )
    session.commit()


def business_named(session: Session, name: str) -> Business:
    return session.exec(select(Business).where(Business.name == name)).one()


def customer_with_code(session: Session, business: Business, code: str) -> Customer:
    return session.exec(
        select(Customer).where(Customer.business_id == business.id, Customer.code == code)
    ).one()


def purchases_with_prefix(session: Session, prefix: str) -> list[Purchase]:
    rows = session.exec(
        select(Purchase)
        .where(Purchase.idempotency_key.like(f"{prefix}%"))
        .order_by(Purchase.idempotency_key)
    ).all()
    return list(rows)


class TestGuards:
    def test_bulk_requires_the_demo_businesses(self, session: Session) -> None:
        with pytest.raises(SimulateError, match="scripts.seed"):
            bulk(session)

    def test_tick_requires_the_demo_businesses(self, session: Session) -> None:
        with pytest.raises(SimulateError, match="scripts.seed"):
            tick(session, now=NOW)

    def test_cli_without_mode_fails(self) -> None:
        with pytest.raises(SystemExit):
            main([])

    def test_missing_cashier_is_reported(self, session: Session) -> None:
        seed(session, PASSWORD)
        caja = session.exec(select(User).where(User.email == "caja@cafe-aurora.mx")).one()
        caja.email = "caja.moved@example.com"
        session.add(caja)
        session.commit()
        with pytest.raises(SimulateError, match="cashier"):
            bulk(session, now=NOW)

    def test_business_without_tiers_is_reported(self, session: Session) -> None:
        minimal_businesses(session, with_tiers=False)
        with pytest.raises(SimulateError, match="no tiers"):
            bulk(session, now=NOW)

    def test_business_without_admin_is_reported(self, session: Session) -> None:
        minimal_businesses(session, with_admin=False)
        with pytest.raises(SimulateError, match="no admin"):
            bulk(session, now=NOW)

    def test_card_code_collision_is_reported(self, session: Session) -> None:
        seed(session, PASSWORD)
        aurora = business_named(session, "Café Aurora")
        tier = session.exec(select(Tier).where(Tier.business_id == aurora.id)).first()
        session.add(
            Customer(
                business_id=aurora.id,
                tier_id=tier.id,
                code=extra_code("aurora", 1),  # the first generated code
                full_name="Conflicto Total",
                email="conflicto@correo.com",
                issued_at=NOW,
                valid_until=NOW + timedelta(days=30),
            )
        )
        session.commit()
        with pytest.raises(SimulateError, match="already used"):
            bulk(session, now=NOW)

    def test_history_skips_businesses_without_eligible_customers(self, session: Session) -> None:
        seed(session, PASSWORD)
        businesses = load_businesses(session)
        for customer in session.exec(select(Customer)).all():
            customer.cancelled_at = NOW - timedelta(days=100)
            session.add(customer)
        session.commit()
        assert history(session, businesses, NOW, days=7, rng=random.Random(1)) == []
        assert purchases_with_prefix(session, "demo-") == []


class TestCharge:
    def test_active_card_applies_benefits(self, session: Session) -> None:
        seed(session, PASSWORD)
        aurora = business_named(session, "Café Aurora")
        laura = customer_with_code(session, aurora, "MP-4F7K2")  # Oro: 15 %, 1 pt/$10, 3 %
        caja = session.exec(select(User).where(User.email == "caja@cafe-aurora.mx")).one()
        before = balance_of(session, aurora.id, laura.id)
        purchase = charge(
            session,
            aurora,
            laura,
            caja,
            NOW - timedelta(days=1),
            100_000,
            "Café y pan dulce",
            idempotency_key="test-0001",
        )
        assert purchase.discount_percent == Decimal("15")
        assert purchase.discount_cents == 15_000
        assert purchase.total_cents == 85_000
        assert purchase.points_earned == 85
        assert purchase.cashback_earned_cents == 2_550
        assert purchase.card_status is CardStatus.ACTIVE
        # Laura already has seed purchases: the snapshot adds to that balance.
        assert purchase.points_balance_after == before.points + 85
        assert purchase.cashback_balance_after_cents == before.cashback_cents + 2_550

    def test_expired_card_has_no_benefits(self, session: Session) -> None:
        seed(session, PASSWORD)
        aurora = business_named(session, "Café Aurora")
        ricardo = customer_with_code(session, aurora, "MP-6QXZ9")  # issued 400 days ago
        assert as_utc(ricardo.valid_until) < NOW

        caja = session.exec(select(User).where(User.email == "caja@cafe-aurora.mx")).one()
        purchase = charge(
            session,
            aurora,
            ricardo,
            caja,
            NOW,
            9_000,
            "Café y galletas",
            idempotency_key="test-0002",
        )
        assert purchase.card_status is CardStatus.EXPIRED
        assert purchase.discount_cents == 0
        assert purchase.total_cents == 9_000
        assert purchase.points_earned == 0
        assert purchase.cashback_earned_cents == 0

    def test_cancelled_card_after_cancellation_is_refused(self, session: Session) -> None:
        seed(session, PASSWORD)
        aurora = business_named(session, "Café Aurora")
        daniela = customer_with_code(session, aurora, "MP-4YGK8")
        assert daniela.cancelled_at is not None

        caja = session.exec(select(User).where(User.email == "caja@cafe-aurora.mx")).one()
        with pytest.raises(SimulateError, match="cancelled"):
            charge(session, aurora, daniela, caja, NOW, 15_000, "Frappé")

    def test_charges_accumulate_per_customer(self, session: Session) -> None:
        seed(session, PASSWORD)
        aurora = business_named(session, "Café Aurora")
        laura = customer_with_code(session, aurora, "MP-4F7K2")

        caja = session.exec(select(User).where(User.email == "caja@cafe-aurora.mx")).one()
        first = charge(
            session,
            aurora,
            laura,
            caja,
            NOW - timedelta(days=2),
            50_000,
            "Brunch",
            idempotency_key="test-0003",
        )
        second = charge(
            session,
            aurora,
            laura,
            caja,
            NOW - timedelta(days=1),
            50_000,
            "Brunch",
            idempotency_key="test-0004",
        )
        assert second.points_balance_after == first.points_balance_after + second.points_earned
        assert (
            second.cashback_balance_after_cents
            == first.cashback_balance_after_cents
            - second.cashback_used_cents
            + second.cashback_earned_cents
        )


class TestBulk:
    def test_creates_history_and_customers(self, session: Session) -> None:
        seed(session, PASSWORD)
        seed_purchases = len(purchases_with_prefix(session, "seed-"))

        created = bulk(session, now=NOW, rng=random.Random(20261))

        assert len(purchases_with_prefix(session, "seed-")) == seed_purchases  # untouched
        demo = purchases_with_prefix(session, "demo-")
        assert len(demo) > 150
        assert any(line.startswith("created   purchase") for line in created)

        extras = session.exec(select(Customer).where(Customer.email.like("demo.%"))).all()
        assert len(extras) == 20
        # Every generated customer with a priced tier got its first payment.
        extra_ids = [customer.id for customer in extras]
        payments = session.exec(
            select(MembershipPayment).where(MembershipPayment.customer_id.in_(extra_ids))  # type: ignore[attr-defined]
        ).all()
        expected = 0
        for customer in extras:
            tier = session.get(Tier, customer.tier_id)
            if tier.price_cents > 0:
                expected += 1
        assert len(payments) == expected
        assert expected > 0

    def test_is_refused_on_a_second_run(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        before = len(purchases_with_prefix(session, "demo-"))
        with pytest.raises(SimulateError, match="already exists"):
            bulk(session, now=NOW, rng=random.Random(20261))
        assert len(purchases_with_prefix(session, "demo-")) == before

    def test_is_reproducible(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, days=7, rng=random.Random(20261))
        first = [
            (
                row.idempotency_key,
                row.customer_id,
                row.amount_cents,
                row.concept,
                row.created_at.isoformat(),
            )
            for row in purchases_with_prefix(session, "demo-")
        ]
        assert first

        for row in purchases_with_prefix(session, "demo-"):
            session.delete(row)
        session.commit()

        bulk(session, now=NOW, days=7, rng=random.Random(20261))
        second = [
            (
                row.idempotency_key,
                row.customer_id,
                row.amount_cents,
                row.concept,
                row.created_at.isoformat(),
            )
            for row in purchases_with_prefix(session, "demo-")
        ]
        assert second == first

    def test_respects_card_windows(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        aurora = business_named(session, "Café Aurora")

        ricardo = customer_with_code(session, aurora, "MP-6QXZ9")
        ricardo_rows = session.exec(
            select(Purchase).where(Purchase.customer_id == ricardo.id)
        ).all()
        saw_active = saw_expired = False
        for row in ricardo_rows:
            if as_utc(row.created_at) >= as_utc(ricardo.valid_until):
                saw_expired = True
                assert row.card_status is CardStatus.EXPIRED
                assert row.discount_cents == 0
                assert row.points_earned == 0
            else:
                saw_active = True
                assert row.card_status is CardStatus.ACTIVE
        assert saw_active and saw_expired

        daniela = customer_with_code(session, aurora, "MP-4YGK8")
        daniela_rows = session.exec(
            select(Purchase).where(Purchase.customer_id == daniela.id)
        ).all()
        assert daniela_rows  # she bought while the card was alive
        for row in daniela_rows:
            assert as_utc(row.created_at) < as_utc(daniela.cancelled_at)

    def test_hours_are_business_hours(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        for row in purchases_with_prefix(session, "demo-"):
            hour = as_utc(row.created_at).hour
            assert hour >= 15 or hour <= 2  # 7:00-18:59 in Tijuana (UTC-8)

    def test_generated_names_pass_the_name_rule(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        extras = session.exec(select(Customer).where(Customer.email.like("demo.%"))).all()
        assert extras
        for customer in extras:
            assert normalize_person_name(customer.full_name) == customer.full_name

    def test_codes_do_not_collide(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        for name in ("Café Aurora", "Gimnasio Titán"):
            business = business_named(session, name)
            codes = session.exec(
                select(Customer.code).where(Customer.business_id == business.id)
            ).all()
            assert len(codes) == len(set(codes))

    def test_generated_codes_follow_the_numeric_rule(self, session: Session) -> None:
        # docs/REVISION.md (Numeración): MP- plus 5 chars, no 0/O/1/I/L, not sequential.
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        pattern = re.compile(r"^MP-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{5}$")
        extras = session.exec(select(Customer).where(Customer.email.like("demo.%"))).all()
        assert extras
        for customer in extras:
            assert pattern.fullmatch(customer.code)

    def test_only_touches_the_demo_businesses(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        ids = {
            business_named(session, name).id
            for name in ("Café Aurora", "Gimnasio Titán", "Abarrotes Sol")
        }
        for row in purchases_with_prefix(session, "demo-"):
            assert row.business_id in ids

    def test_sol_takes_purchases_but_not_customers(self, session: Session) -> None:
        """Free plan: purchases are not a capacity, cards are (see plan_service).

        Adding purchases to Abarrotes Sol keeps the 409 `limit_reached` real:
        `usage` still counts exactly `SOL_CUSTOMERS_COUNT` live cards.
        """
        seed(session, PASSWORD)
        sol = business_named(session, "Abarrotes Sol")
        before = session.exec(select(Customer).where(Customer.business_id == sol.id)).all()
        assert len(before) == SOL_CUSTOMERS_COUNT

        bulk(session, now=NOW, rng=random.Random(20261))

        sol_purchases = session.exec(
            select(Purchase).where(Purchase.business_id == sol.id)
        ).all()
        assert any(row.idempotency_key.startswith("demo-") for row in sol_purchases)
        after = session.exec(select(Customer).where(Customer.business_id == sol.id)).all()
        assert len(after) == SOL_CUSTOMERS_COUNT
        assert all(not customer.email.startswith("demo.") for customer in after)

    def test_marks_cards_as_expiring_soon(self, session: Session) -> None:
        seed(session, PASSWORD)
        bulk(session, now=NOW, rng=random.Random(20261))
        extras = session.exec(select(Customer).where(Customer.email.like("demo.%"))).all()
        for name in ("Café Aurora", "Gimnasio Titán"):
            business = business_named(session, name)
            soon = [
                customer
                for customer in extras
                if customer.business_id == business.id
                and NOW < as_utc(customer.valid_until) <= NOW + timedelta(days=40)
            ]
            assert len(soon) >= 2


class TestTick:
    def test_inserts_one_or_two_purchases_now(self, session: Session) -> None:
        seed(session, PASSWORD)
        for index in range(6):
            moment = NOW + timedelta(minutes=index)
            result = tick(session, now=moment, rng=random.Random(index))
            assert 1 <= len(result.created) <= 2
        rows = purchases_with_prefix(session, "sim-")
        assert len(rows) >= 6
        for row in rows:
            assert NOW <= as_utc(row.created_at) <= NOW + timedelta(minutes=5)
            assert row.idempotency_key.startswith("sim-")

    def test_same_minute_does_not_duplicate(self, session: Session) -> None:
        seed(session, PASSWORD)
        first = tick(session, now=NOW, rng=random.Random(1))
        assert first.created
        after_first = len(purchases_with_prefix(session, "sim-"))
        second = tick(session, now=NOW, rng=random.Random(2))
        assert second.skipped is True
        assert len(purchases_with_prefix(session, "sim-")) == after_first

    def test_alternates_businesses(self, session: Session) -> None:
        seed(session, PASSWORD)
        ids = {
            business_named(session, name).id
            for name in ("Café Aurora", "Gimnasio Titán", "Abarrotes Sol")
        }
        seen: set[int] = set()
        for index in range(3):
            tick(session, now=NOW + timedelta(minutes=index), rng=random.Random(3 + index))
            seen |= {row.business_id for row in purchases_with_prefix(session, "sim-")}
        assert seen == ids  # three minutes in a row rotate over the three businesses

    def test_only_picks_active_cards(self, session: Session) -> None:
        seed(session, PASSWORD)
        aurora = business_named(session, "Café Aurora")
        ricardo = customer_with_code(session, aurora, "MP-6QXZ9")  # expired
        daniela = customer_with_code(session, aurora, "MP-4YGK8")  # cancelled
        for index in range(8):
            tick(session, now=NOW + timedelta(minutes=index), rng=random.Random(10 + index))
        for row in purchases_with_prefix(session, "sim-"):
            assert row.customer_id not in {ricardo.id, daniela.id}

    def test_without_active_customers_exits_clean(self, session: Session) -> None:
        seed(session, PASSWORD)
        for customer in session.exec(select(Customer)).all():
            customer.cancelled_at = NOW
            session.add(customer)
        session.commit()
        result = tick(session, now=NOW, rng=random.Random(5))
        assert result.created == []
        assert purchases_with_prefix(session, "sim-") == []


class TestMain:
    def test_bulk_prints_created(
        self, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seed(session, PASSWORD)
        assert main(["--bulk", "--days", "5"]) == 0
        out = capsys.readouterr().out
        assert "created   purchase" in out
        assert "History ready" in out

    def test_tick_prints_created(
        self, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seed(session, PASSWORD)
        assert main(["--tick"]) == 0
        out = capsys.readouterr().out
        assert "created   purchase" in out

    def test_tick_is_a_noop_in_the_same_minute(
        self,
        session: Session,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        seed(session, PASSWORD)
        monkeypatch.setattr("scripts.simulate.utc_now", lambda: NOW)
        assert main(["--tick"]) == 0
        capsys.readouterr()
        assert main(["--tick"]) == 0
        assert capsys.readouterr().out == ""

    def test_without_demo_data_returns_1(
        self, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--tick"]) == 1
        assert "Simulation aborted" in capsys.readouterr().err
