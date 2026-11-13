"""Demo data: two businesses that must never see each other, their users and tiers.

Run after the migrations:

    uv run alembic upgrade head
    uv run python -m scripts.seed

It is idempotent: anything that already exists (business by name, user by
email, tier by business and name) is left untouched, so it can run any number
of times. It never changes an existing user's password or an edited tier.

Password for the demo users:
- SEED_PASSWORD from the environment or .env, if set (at least 8 characters).
- Otherwise, only when ENVIRONMENT=development, the known demo password below.
- In production SEED_PASSWORD is required: the script refuses to run without it.
"""

import sys
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from core.config import settings
from core.security import hash_password
from db.database import engine
from models import Business, BusinessStatus, Role, Tier, TierFinish, User

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

# (business key, name, finish, min_points, discount %, points per $10, cashback %)
# Café Aurora follows the API contract (section 8). Gimnasio Titán gets different
# tiers on purpose: the frontend's isolation check compares both businesses.
TIERS = [
    ("aurora", "Bronce", TierFinish.BRONZE, 0, "5", 1, "0"),
    ("aurora", "Plata", TierFinish.SILVER, 400, "10", 1, "1"),
    ("aurora", "Oro", TierFinish.GOLD, 1000, "15", 1, "3"),
    ("aurora", "Onyx", TierFinish.ONYX, 1500, "20", 2, "5"),
    ("titan", "Básico", TierFinish.SILVER, 0, "0", 1, "0"),
    ("titan", "Premium", TierFinish.ONYX, 800, "10", 2, "2"),
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

    for key, name, finish, min_points, discount, points, cashback in TIERS:
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
                min_points=min_points,
                discount_percent=Decimal(discount),
                points_per_ten=points,
                cashback_percent=Decimal(cashback),
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
