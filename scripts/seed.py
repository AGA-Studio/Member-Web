"""Demo data: two businesses that must never see each other, with users, tiers and customers.

Run after the migrations:

    uv run alembic upgrade head
    uv run python -m scripts.seed

It is idempotent: anything that already exists (business by name, user by
email, tier by business and name, customer by business and email) is left
untouched, so it can run any number of times. It never changes an existing user's
password or an edited tier.

Password for the demo users:
- SEED_PASSWORD from the environment or .env, if set (at least 8 characters).
- Otherwise, only when ENVIRONMENT=development, the known demo password below.
- In production SEED_PASSWORD is required: the script refuses to run without it.
"""

import sys
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlmodel import Session, select

from core.config import settings
from core.security import hash_password
from db.database import engine
from models import Business, BusinessStatus, Customer, Role, Tier, TierFinish, User
from services.customer_service import VALIDITY_MONTHS, add_months, utc_now

DEMO_PASSWORD = "demo12345"
MIN_PASSWORD_LENGTH = 8

BUSINESSES = [
    {"key": "aurora", "name": "Café Aurora"},
    {"key": "titan", "name": "Gimnasio Titán"},
]

# (email, name, role, business key or None for the platform owner)
USERS = [
    ("owner@memberplus.mx", "Equipo Member", Role.PLATFORM, None),
    ("admin@cafe-aurora.mx", "Ana Torres", Role.ADMIN, "aurora"),
    ("caja@cafe-aurora.mx", "Luis Pérez", Role.EMPLOYEE, "aurora"),
    ("admin@gimnasio-titan.mx", "Marco Ruiz", Role.ADMIN, "titan"),
]

# (business key, name, finish, price in cents, discount %, points per $10, cashback %)
# Café Aurora uses the benefits of the API contract (section 8); the prices are demo
# values (a better tier costs more). Gimnasio Titán gets different tiers on purpose:
# the frontend's isolation check compares both businesses.
TIERS = [
    ("aurora", "Bronce", TierFinish.BRONZE, 0, "5", 1, "0"),
    ("aurora", "Plata", TierFinish.SILVER, 19_900, "10", 1, "1"),
    ("aurora", "Oro", TierFinish.GOLD, 39_900, "15", 1, "3"),
    ("aurora", "Onyx", TierFinish.ONYX, 69_900, "20", 2, "5"),
    ("titan", "Básico", TierFinish.SILVER, 29_900, "0", 1, "0"),
    ("titan", "Premium", TierFinish.ONYX, 59_900, "10", 2, "2"),
]

# (business key, code, full name, email, phone, tier, card issued N days ago, cancelled)
# Card valid for 12 months: issued 345-350 days ago = expiring soon, 400 = expired.
# Fixed codes so the demo QR cards keep working after a reseed.
CUSTOMERS = [
    (
        "aurora",
        "MP-4F7K2",
        "Laura Méndez",
        "laura.mendez@correo.com",
        "664 123 4567",
        "Oro",
        240,
        False,
    ),
    (
        "aurora",
        "MP-7H3QX",
        "Carlos Ramírez",
        "carlos.ramirez@correo.com",
        None,
        "Plata",
        120,
        False,
    ),
    (
        "aurora",
        "MP-9KD2M",
        "Sofía Hernández",
        "sofia.hernandez@correo.com",
        "664 222 1010",
        "Onyx",
        60,
        False,
    ),
    (
        "aurora",
        "MP-2RW8T",
        "Diego Castillo",
        "diego.castillo@correo.com",
        None,
        "Bronce",
        30,
        False,
    ),
    (
        "aurora",
        "MP-5NBV7",
        "Valeria Ortiz",
        "valeria.ortiz@correo.com",
        "664 333 2020",
        "Plata",
        345,
        False,
    ),
    (
        "aurora",
        "MP-8TPC4",
        "Javier Morales",
        "javier.morales@correo.com",
        None,
        "Bronce",
        350,
        False,
    ),
    (
        "aurora",
        "MP-3MJ6H",
        "Fernanda Ruiz",
        "fernanda.ruiz@correo.com",
        "664 444 3030",
        "Oro",
        200,
        False,
    ),
    (
        "aurora",
        "MP-6QXZ9",
        "Ricardo Flores",
        "ricardo.flores@correo.com",
        None,
        "Bronce",
        400,
        False,
    ),
    (
        "aurora",
        "MP-4YGK8",
        "Daniela Vega",
        "daniela.vega@correo.com",
        "664 555 4040",
        "Plata",
        90,
        True,
    ),
    ("aurora", "MP-7WFR3", "Andrés Navarro", "andres.navarro@correo.com", None, "Onyx", 10, False),
    (
        "aurora",
        "MP-2CHN5",
        "Mariana Jiménez",
        "mariana.jimenez@correo.com",
        "664 666 5050",
        "Oro",
        150,
        False,
    ),
    ("aurora", "MP-9VTB6", "Emilio Soto", "emilio.soto@correo.com", None, "Bronce", 5, False),
    (
        "titan",
        "MP-3GYM4",
        "Roberto Díaz",
        "roberto.diaz@correo.com",
        "664 777 6060",
        "Premium",
        100,
        False,
    ),
    ("titan", "MP-8FTX2", "Paola Cruz", "paola.cruz@correo.com", None, "Básico", 50, False),
]


class SeedError(Exception):
    """The seed cannot run safely (for example, no password in production)."""


@dataclass
class SeedResult:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)


def resolve_password() -> str:
    password = settings.seed_password
    if password:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise SeedError(f"SEED_PASSWORD must have at least {MIN_PASSWORD_LENGTH} characters")
        return password
    if settings.environment == "development":
        return DEMO_PASSWORD
    raise SeedError("SEED_PASSWORD is required when ENVIRONMENT is not development")


def seed(session: Session, password: str) -> SeedResult:
    result = SeedResult()

    businesses: dict[str, Business] = {}
    for spec in BUSINESSES:
        business = session.exec(select(Business).where(Business.name == spec["name"])).first()
        if business is None:
            business = Business(name=spec["name"], status=BusinessStatus.ACTIVE)
            session.add(business)
            session.flush()
            result.created.append(f"business  {spec['name']}")
        else:
            result.existing.append(f"business  {spec['name']}")
        businesses[spec["key"]] = business

    hashed = hash_password(password)  # Argon2id is slow: hash once for every user.
    for email, name, role, business_key in USERS:
        if session.exec(select(User).where(User.email == email)).first() is not None:
            result.existing.append(f"user      {email}")
            continue
        business = businesses[business_key] if business_key else None
        session.add(
            User(
                business_id=business.id if business else None,
                name=name,
                email=email,
                hashed_password=hashed,
                role=role,
            )
        )
        result.created.append(f"user      {email} ({role})")

    for key, name, finish, price_cents, discount, points, cashback in TIERS:
        business = businesses[key]
        label = f"tier      {business.name} / {name}"
        query = select(Tier).where(Tier.business_id == business.id, Tier.name == name)
        if session.exec(query).first() is not None:
            result.existing.append(label)
            continue
        session.add(
            Tier(
                business_id=business.id,
                name=name,
                finish=finish,
                price_cents=price_cents,
                discount_percent=Decimal(discount),
                points_per_ten=points,
                cashback_percent=Decimal(cashback),
            )
        )
        result.created.append(label)
    session.flush()

    now = utc_now()
    for key, code, name, email, phone, tier_name, days_ago, cancelled in CUSTOMERS:
        business = businesses[key]
        label = f"customer  {business.name} / {email}"
        query = select(Customer).where(Customer.business_id == business.id, Customer.email == email)
        if session.exec(query).first() is not None:
            result.existing.append(label)
            continue
        tier = session.exec(
            select(Tier).where(Tier.business_id == business.id, Tier.name == tier_name)
        ).one()
        issued_at = now - timedelta(days=days_ago)
        session.add(
            Customer(
                business_id=business.id,
                tier_id=tier.id,
                code=code,
                full_name=name,
                email=email,
                phone=phone,
                issued_at=issued_at,
                valid_until=add_months(issued_at, VALIDITY_MONTHS),
                cancelled_at=now - timedelta(days=7) if cancelled else None,
            )
        )
        result.created.append(label)

    session.commit()
    return result


def main() -> int:
    try:
        password = resolve_password()
    except SeedError as error:
        print(f"Seed aborted: {error}", file=sys.stderr)
        return 1

    with Session(engine) as session:
        result = seed(session, password)

    for line in result.created:
        print(f"created   {line}")
    for line in result.existing:
        print(f"exists    {line}")
    if result.created and password == DEMO_PASSWORD:
        print(f"\nDemo password for the new users: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
