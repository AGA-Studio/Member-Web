"""Plans of the SaaS: the catalog and the plan a business has right now (issue #70).

Rules (wiki, "Planes y límites: propuesta"):
- The effective plan is computed when read, never by a scheduled job:
  no plan assigned → the default plan; a trial that already ended → the default
  plan; otherwise the assigned plan. Like the points balance, nothing is stored
  that a clock could leave out of date.
- `status` (trial/active/suspended) is access; the plan is capabilities. A trial
  ending never suspends a business, deletes anything or switches off a card.
- The numbers of `CATALOG` are the starting suggestion of the proposal, not a
  commitment: the team fixes them when it marks *¿Hay planes y cobro?*. Changing
  them is a new migration (the catalog is data) plus this list (tests and seed).
"""

from datetime import datetime

from sqlmodel import Session, select

from models.business_model import Business
from models.plan_model import Plan
from services.customer_service import as_utc, utc_now

# key, name, price_cents, customers, users, devices, history_days,
# images, exports, ai, ai_messages_month, trial_days, is_default, is_public
CATALOG: list[dict] = [
    {
        "key": "free",
        "name": "Gratis",
        "price_cents": 0,
        "max_customers": 50,
        "max_users": 2,
        "max_devices": 0,
        "history_days": 60,
        "images_enabled": False,
        "exports_enabled": False,
        "ai_enabled": False,
        "ai_messages_month": 0,
        "trial_days": 0,
        "is_default": True,
        "is_public": True,
        "sort_order": 0,
    },
    {
        "key": "counter",
        "name": "Mostrador",
        "price_cents": 19_900,
        "max_customers": 300,
        "max_users": 3,
        "max_devices": 1,
        "history_days": 365,
        "images_enabled": True,
        "exports_enabled": True,
        "ai_enabled": False,
        "ai_messages_month": 0,
        "trial_days": 0,
        "is_default": False,
        "is_public": True,
        "sort_order": 1,
    },
    {
        "key": "business",
        "name": "Negocio",
        "price_cents": 39_900,
        "max_customers": 1_000,
        "max_users": 8,
        "max_devices": 2,
        "history_days": None,
        "images_enabled": True,
        "exports_enabled": True,
        "ai_enabled": True,
        "ai_messages_month": 100,
        "trial_days": 30,
        "is_default": False,
        "is_public": True,
        "sort_order": 2,
    },
    {
        "key": "chain",
        "name": "Cadena",
        "price_cents": 79_900,
        "max_customers": 3_000,
        "max_users": 20,
        "max_devices": 5,
        "history_days": None,
        "images_enabled": True,
        "exports_enabled": True,
        "ai_enabled": True,
        "ai_messages_month": 300,
        "trial_days": 0,
        "is_default": False,
        # "Después" in the proposal: assigned by hand, not offered yet.
        "is_public": False,
        "sort_order": 3,
    },
]
DEFAULT_KEY = "free"


def ensure_catalog(session: Session) -> None:
    """Insert the plans of `CATALOG` that do not exist yet (by `key`).

    Existing plans are left as they are: an edited price is never overwritten.
    The migration loads the same rows in production; this is for the seed and
    for the tests, whose tables `create_all` builds without data.
    """
    existing = set(session.exec(select(Plan.key)).all())
    for row in CATALOG:
        if row["key"] not in existing:
            session.add(Plan(**row))
    session.commit()


def default_plan(session: Session) -> Plan:
    plan = session.exec(select(Plan).where(Plan.is_default.is_(True))).first()  # type: ignore[attr-defined]
    if plan is None:
        raise RuntimeError("No default plan: run the migrations (or plan_service.ensure_catalog)")
    return plan


def get_by_key(session: Session, key: str) -> Plan | None:
    return session.exec(select(Plan).where(Plan.key == key)).first()


def public_plans(session: Session) -> list[Plan]:
    """The plans a business can pick, cheapest first."""
    query = select(Plan).where(Plan.is_public.is_(True)).order_by(Plan.sort_order, Plan.id)  # type: ignore[attr-defined]
    return list(session.exec(query).all())


def trial_active(business: Business, now: datetime | None = None) -> bool:
    if business.trial_ends_at is None:
        return False
    return as_utc(business.trial_ends_at) > (now or utc_now())


def effective_plan(session: Session, business: Business, now: datetime | None = None) -> Plan:
    """The plan whose limits and capabilities apply to `business` right now."""
    if business.plan_id is None:
        return default_plan(session)
    if business.trial_ends_at is not None and not trial_active(business, now):
        return default_plan(session)
    plan = session.get(Plan, business.plan_id)
    return plan if plan is not None else default_plan(session)
