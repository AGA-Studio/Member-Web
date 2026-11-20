"""Demo data simulator: weeks of history in one shot plus a "now" tick.

    python -m scripts.simulate --bulk [--days 84]   # once per database
    python -m scripts.simulate --tick               # Coolify scheduled task

Same rules as `scripts/seed.py`: writes straight to the database (the scripts
run without the RLS tenant role, like the seed and the migrations), prices
every purchase through `services.pricing_service` with the card status at that
moment, and walks the events in chronological order so the per-customer
balances accumulate exactly like the checkout does.

Nothing here edits existing rows: `--bulk` refuses to run on a database that
already has `demo-` purchases (to regenerate, reset the database the way the
seed reset documents), and `--tick` appends at most once per minute, so a
scheduled run and a manual "Run now" in Coolify never double-charge.

The purchase block duplicates `scripts/seed.py` on purpose: the seed is pinned
by `tests/scripts/test_seed.py` (fixed dataset and counts), so moving its block
here would churn a tested file without changing behavior.

Snapshots (`points_balance_after`, `cashback_balance_after_cents`) of
backdated rows are computed at insert time against the rows that already
exist, just like any extension of the seed; the live balances the UI shows are
always recomputed from the purchase history
(`services.customer_service.balance_of`).
"""

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, select

from db.database import engine
from models import (
    Business,
    CardStatus,
    Customer,
    MembershipPayment,
    PaymentKind,
    PaymentMethod,
    Purchase,
    Role,
    Tier,
    User,
)
from services import pricing_service
from services.customer_service import add_months, as_utc, balance_of, utc_now

# Demos are keyed the same way as the seed: short key -> business name.
DEMO_BUSINESSES = [("aurora", "Café Aurora"), ("titan", "Gimnasio Titán")]

# Both prefixes are namespaced apart from the seed's `seed-NN` keys.
BULK_PREFIX = "demo-"
TICK_PREFIX = "sim-"

BULK_DAYS = 84
RNG_SEED = 20261
CASHBACK_CHANCE = 0.15
TWO_PURCHASES_CHANCE = 0.3

CASHIER_EMAILS = {"aurora": "caja@cafe-aurora.mx", "titan": "admin@gimnasio-titan.mx"}

# (concept, low cents, high cents) per business. Amounts land on the receipt
# as-is, so they are drawn from realistic menus, not arbitrary ranges.
MENUS = {
    "aurora": [
        ("Café solo", 3_500, 5_500),
        ("Capuchino y croissant", 8_000, 12_000),
        ("Frappé y sándwich", 12_000, 18_000),
        ("Brunch", 15_000, 22_000),
        ("Desayuno para dos", 26_000, 34_000),
        ("Pastel por encargo", 38_000, 45_000),
    ],
    "titan": [
        ("Day pass", 8_000, 10_000),
        ("Proteína en barra", 9_000, 14_000),
        ("Renta de casillero", 15_000, 20_000),
        ("Clase personalizada", 45_000, 60_000),
    ],
}

# Purchases per day: a café sells more often than a gym.
DAILY_MAX = {"aurora": 4, "titan": 2}

# Generated customers: fixed names (they must pass the API name rule), a fixed
# email series and a deterministic card-code series, so a fresh database always
# gets the same demo people.
EXTRA_CUSTOMER_NAMES = {
    "aurora": [
        "Alejandro Vega",
        "Camila Torres",
        "Jorge Medina",
        "Paulina Ríos",
        "Iván Delgado",
        "Regina Castro",
        "Óscar Pineda",
        "Luciana Bravo",
        "Martín Salas",
        "Ximena Cortés",
    ],
    "titan": [
        "Emilio Fuentes",
        "Renata Aguilar",
        "Hugo Serrano",
        "Valeria Nava",
        "Bruno Lara",
        "Mariana Peña",
        "Felipe Rojas",
        "Daniela Ibarra",
        "Sergio Maldonado",
        "Ana Lucía Ferrer",
    ],
}
EXTRA_EMAIL_DOMAINS = {"aurora": "cafe-aurora.mx", "titan": "gimnasio-titan.mx"}
# MP-D1… / MP-D2… : deterministic, unlike `generate_code()` (secrets).
EXTRA_CODE_SERIES = {"aurora": "MP-D1", "titan": "MP-D2"}


class SimulateError(Exception):
    """The simulator cannot run safely (missing demo data, already seeded...)."""


@dataclass
class TickResult:
    created: list[str] = field(default_factory=list)
    skipped: bool = False


def card_status_at(customer: Customer, moment: datetime) -> CardStatus:
    """Status the card had at `moment` (history is written in the past).

    Copied from `scripts/seed.py`: the checkout computes the same three states
    and only an ACTIVE card gets the tier benefits.
    """
    if customer.cancelled_at is not None and as_utc(customer.cancelled_at) <= moment:
        return CardStatus.CANCELLED
    if as_utc(customer.valid_until) <= moment:
        return CardStatus.EXPIRED
    return CardStatus.ACTIVE


def load_businesses(session: Session) -> dict[str, Business]:
    found: dict[str, Business] = {}
    for key, name in DEMO_BUSINESSES:
        business = session.exec(select(Business).where(Business.name == name)).first()
        if business is None:
            raise SimulateError(
                f"the demo business «{name}» does not exist; run `python -m scripts.seed` first"
            )
        found[key] = business
    return found


def load_cashiers(session: Session, businesses: dict[str, Business]) -> dict[str, User]:
    cashiers: dict[str, User] = {}
    for key, email in CASHIER_EMAILS.items():
        cashier = session.exec(
            select(User).where(User.email == email, User.business_id == businesses[key].id)
        ).first()
        if cashier is None:
            raise SimulateError(
                f"the demo cashier {email} does not exist; run `python -m scripts.seed` first"
            )
        cashiers[key] = cashier
    return cashiers


def charge(
    session: Session,
    business: Business,
    customer: Customer,
    cashier: User,
    moment: datetime,
    amount_cents: int,
    concept: str,
    *,
    use_cashback: bool = False,
    idempotency_key: str | None = None,
) -> Purchase:
    """Insert one purchase with the same math the checkout applies.

    Mirrors the purchase block of `scripts/seed.py` (tier benefits only when
    the card was ACTIVE at `moment`, cashback capped by the balance, snapshot
    columns on the row) and flushes so the next charge of the same customer
    sees the updated balance.
    """
    status_at = card_status_at(customer, moment)
    if status_at is CardStatus.CANCELLED:
        raise SimulateError(
            f"card {customer.code} was cancelled before {moment.isoformat()}; it cannot be charged"
        )
    tier = session.get(Tier, customer.tier_id)
    balance = balance_of(session, business.id, customer.id)
    applied = pricing_service.calculate(
        amount_cents,
        discount_percent=tier.discount_percent,
        points_per_ten=tier.points_per_ten,
        cashback_percent=tier.cashback_percent,
        cashback_balance_cents=balance.cashback_cents,
        use_cashback=use_cashback and balance.cashback_cents > 0,
        benefits_apply=status_at is CardStatus.ACTIVE,
    )
    purchase = Purchase(
        business_id=business.id,
        customer_id=customer.id,
        cashier_id=cashier.id,
        tier_id=tier.id,
        tier_name=tier.name,
        tier_finish=tier.finish,
        card_status=status_at,
        concept=concept,
        amount_cents=amount_cents,
        discount_percent=applied.discount_percent,
        discount_cents=applied.discount_cents,
        cashback_used_cents=applied.cashback_used_cents,
        total_cents=applied.total_cents,
        points_earned=applied.points_earned,
        cashback_earned_cents=applied.cashback_earned_cents,
        points_balance_after=balance.points + applied.points_earned,
        cashback_balance_after_cents=(
            balance.cashback_cents - applied.cashback_used_cents + applied.cashback_earned_cents
        ),
        idempotency_key=idempotency_key,
        created_at=moment,
    )
    session.add(purchase)
    session.flush()  # the next charge of this customer sees the new balance
    return purchase


def extra_customers(session: Session, businesses: dict[str, Business], now: datetime) -> list[str]:
    """The ten generated customers of each business (idempotent by email).

    Two of them per business were issued almost a year ago on purpose: they
    feed the "expiring soon" count of the admin panel.
    """
    created: list[str] = []
    for key, business in businesses.items():
        tiers = session.exec(
            select(Tier).where(Tier.business_id == business.id).order_by(Tier.price_cents, Tier.id)
        ).all()
        if not tiers:
            raise SimulateError(
                f"«{business.name}» has no tiers; run `python -m scripts.seed` first"
            )
        admin = session.exec(
            select(User).where(User.business_id == business.id, User.role == Role.ADMIN)
        ).first()
        if admin is None:
            raise SimulateError(
                f"«{business.name}» has no admin user; run `python -m scripts.seed` first"
            )
        months = business.validity_months
        for index, name in enumerate(EXTRA_CUSTOMER_NAMES[key], start=1):
            email = f"demo.{index:02d}@{EXTRA_EMAIL_DOMAINS[key]}"
            exists = session.exec(
                select(Customer).where(Customer.business_id == business.id, Customer.email == email)
            ).first()
            if exists is not None:
                continue
            code = f"{EXTRA_CODE_SERIES[key]}{index:02d}"
            taken = session.exec(
                select(Customer).where(Customer.business_id == business.id, Customer.code == code)
            ).first()
            if taken is not None:
                raise SimulateError(f"card code {code} is already used in «{business.name}»")
            days_ago = 330 + (index - 1) * 5 if index <= 2 else 10 + index * 6
            issued_at = now - timedelta(days=days_ago)
            tier = tiers[(index - 1) % len(tiers)]
            customer = Customer(
                business_id=business.id,
                tier_id=tier.id,
                code=code,
                full_name=name,
                email=email,
                phone=None if index % 3 == 0 else f"664 000 00{index:02d}",
                issued_at=issued_at,
                valid_until=add_months(issued_at, months),
            )
            session.add(customer)
            session.flush()
            if tier.price_cents > 0:
                session.add(
                    MembershipPayment(
                        business_id=business.id,
                        customer_id=customer.id,
                        tier_id=tier.id,
                        tier_name=tier.name,
                        kind=PaymentKind.NEW,
                        method=PaymentMethod.CASH,
                        amount_cents=tier.price_cents,
                        period_start=issued_at,
                        period_end=customer.valid_until,
                        recorded_by=admin.id,
                        created_at=issued_at,
                    )
                )
            created.append(f"created   customer {business.name} / {email} ({tier.name})")
    session.flush()
    return created


def history(
    session: Session,
    businesses: dict[str, Business],
    now: datetime,
    *,
    days: int = BULK_DAYS,
    rng: random.Random | None = None,
) -> list[str]:
    """Backdated purchases over the last `days`, deterministic per `rng` seed.

    Refuses to run twice: the dataset is a pure function of the fixed inputs
    and the seeded RNG, so a second run would only fight the rows it already
    wrote. To regenerate, reset the database first (seed reset procedure).
    """
    rng = rng or random.Random(RNG_SEED)
    already = session.exec(
        select(Purchase.id).where(Purchase.idempotency_key.like(f"{BULK_PREFIX}%"))  # type: ignore[union-attr]
    ).first()
    if already is not None:
        raise SimulateError(
            "the demo history already exists (`demo-…` purchases); "
            "to regenerate it, reset the database with the seed reset procedure"
        )
    cashiers = load_cashiers(session, businesses)
    pools = {
        key: session.exec(
            select(Customer).where(Customer.business_id == business.id).order_by(Customer.id)
        ).all()
        for key, business in businesses.items()
    }

    # Draw every event first, then walk them in chronological order so each
    # customer's balances accumulate like a real day of sales.
    events: list[tuple[datetime, str, str, int, bool]] = []
    for key, _business in businesses.items():
        for offset in range(days, 0, -1):
            day = now - timedelta(days=offset)
            for _ in range(rng.randint(0, DAILY_MAX[key])):
                hour = 15 + rng.randrange(12)  # 7:00-18:59 in Tijuana (UTC-8)
                moment = day.replace(
                    hour=hour % 24,
                    minute=rng.randrange(60),
                    second=rng.randrange(60),
                    microsecond=0,
                )
                concept, low, high = rng.choice(MENUS[key])
                amount = rng.randint(low, high) // 50 * 50
                events.append((moment, key, concept, amount, rng.random() < CASHBACK_CHANCE))
    events.sort(key=lambda event: event[0])

    created: list[str] = []
    counters = dict.fromkeys(businesses, 0)
    for moment, key, concept, amount, wants_cashback in events:
        pool = [
            customer
            for customer in pools[key]
            if customer.cancelled_at is None or as_utc(customer.cancelled_at) > moment
        ]
        if not pool:
            continue
        customer = rng.choice(pool)
        counters[key] += 1
        purchase_key = f"{BULK_PREFIX}{key}-{counters[key]:04d}"
        charge(
            session,
            businesses[key],
            customer,
            cashiers[key],
            moment,
            amount,
            concept,
            use_cashback=wants_cashback,
            idempotency_key=purchase_key,
        )
        created.append(
            f"created   purchase {businesses[key].name} / {purchase_key} {customer.code}"
        )
    return created


def bulk(
    session: Session,
    *,
    now: datetime | None = None,
    days: int = BULK_DAYS,
    rng: random.Random | None = None,
) -> list[str]:
    """Customers plus weeks of history, in a single transaction."""
    now = now or utc_now()
    businesses = load_businesses(session)
    created = extra_customers(session, businesses, now)
    created += history(session, businesses, now, days=days, rng=rng)
    session.commit()
    return created


def tick(
    session: Session,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> TickResult:
    """One "now" event, for the Coolify scheduled task.

    At most one run per minute: the idempotency keys carry the UTC minute, so
    the cron firing and someone pressing "Run now" in the same minute is a
    no-op, not a double charge. Business selection alternates by minute so a
    demo week touches both tenants.
    """
    now = now or utc_now()
    rng = rng or random.Random()
    businesses = load_businesses(session)
    minute_prefix = f"{TICK_PREFIX}{now:%Y%m%d%H%M}Z-"
    already = session.exec(
        select(Purchase.id).where(Purchase.idempotency_key.like(f"{minute_prefix}%"))  # type: ignore[union-attr]
    ).first()
    if already is not None:
        return TickResult(skipped=True)

    key = DEMO_BUSINESSES[int(now.timestamp() // 60) % len(DEMO_BUSINESSES)][0]
    business = businesses[key]
    active = session.exec(
        select(Customer)
        .where(
            Customer.business_id == business.id,
            Customer.cancelled_at.is_(None),  # type: ignore[union-attr]
            Customer.valid_until > now,
        )
        .order_by(Customer.id)
    ).all()
    if not active:
        print(f"no active customers in {business.name}", file=sys.stderr)
        return TickResult()

    cashier = load_cashiers(session, businesses)[key]
    count = 2 if rng.random() < TWO_PURCHASES_CHANCE else 1
    created: list[str] = []
    for index in range(1, count + 1):
        customer = rng.choice(active)
        concept, low, high = rng.choice(MENUS[key])
        amount = rng.randint(low, high) // 50 * 50
        purchase_key = f"{minute_prefix}{index}"
        charge(
            session,
            business,
            customer,
            cashier,
            now,
            amount,
            concept,
            use_cashback=rng.random() < CASHBACK_CHANCE,
            idempotency_key=purchase_key,
        )
        created.append(f"created   purchase {business.name} / {purchase_key} {customer.code}")
    session.commit()
    return TickResult(created=created)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.simulate",
        description="Demo data: weeks of history (--bulk) or one 'now' purchase (--tick).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--bulk",
        action="store_true",
        help=f"backdated history, once per database ({BULK_DAYS} days by default)",
    )
    mode.add_argument(
        "--tick",
        action="store_true",
        help="one 'now' purchase for the Coolify scheduled task",
    )
    parser.add_argument("--days", type=int, default=BULK_DAYS, help="history length for --bulk")
    args = parser.parse_args(argv)

    try:
        with Session(engine) as session:
            if args.bulk:
                lines = bulk(session, days=args.days)
            else:
                tick_result = tick(session)
                lines = tick_result.created
                if tick_result.skipped:
                    return 0  # this minute is already simulated
    except SimulateError as error:
        print(f"Simulation aborted: {error}", file=sys.stderr)
        return 1

    for line in lines:
        print(line)
    if args.bulk:
        purchases = sum(1 for line in lines if "purchase" in line)
        customers = sum(1 for line in lines if "customer" in line)
        print(f"\nHistory ready: {purchases} purchases, {customers} customers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
