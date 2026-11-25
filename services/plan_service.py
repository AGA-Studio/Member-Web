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

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from fastapi import status
from sqlalchemy import func
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from models.business_model import Business
from models.customer_model import Customer
from models.plan_model import Plan
from models.user_model import User
from schemas.plan_schema import (
    PlanResponse,
    PlanSummaryResponse,
    PlanUsageResponse,
    UsageItemResponse,
)


class Capacity(StrEnum):
    """What a plan counts. Checked only when creating (or reactivating) one."""

    CUSTOMERS = "customers"
    USERS = "users"


class Feature(StrEnum):
    """What a plan switches on or off. Existing data is never removed."""

    IMAGES = "images"
    EXPORTS = "exports"
    AI = "ai"


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


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


# --- Enforcement --------------------------------------------------------------


def _plan_of(session: Session, business_id: int) -> Plan:
    business = session.get(Business, business_id)
    if business is None:
        return default_plan(session)
    return effective_plan(session, business)


def usage(session: Session, business_id: int) -> dict[Capacity, int]:
    """What counts against the limits: non-cancelled cards and active users."""
    customers = session.exec(
        select(func.count())
        .select_from(Customer)
        .where(Customer.business_id == business_id, Customer.cancelled_at.is_(None))  # type: ignore[union-attr]
    ).one()
    users = session.exec(
        select(func.count())
        .select_from(User)
        .where(User.business_id == business_id, User.is_active.is_(True))  # type: ignore[attr-defined]
    ).one()
    return {Capacity.CUSTOMERS: customers, Capacity.USERS: users}


def limit_of(plan: Plan, capacity: Capacity) -> int | None:
    return getattr(plan, f"max_{capacity.value}")


def assert_capacity(session: Session, business_id: int, capacity: Capacity) -> None:
    """409 `limit_reached` when one more would pass the plan's limit."""
    limit = limit_of(_plan_of(session, business_id), capacity)
    if limit is not None and usage(session, business_id)[capacity] >= limit:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The plan allows {limit} {capacity.value}",
            code=ErrorCode.LIMIT_REACHED,
        )


def has_feature(plan: Plan, feature: Feature) -> bool:
    return bool(getattr(plan, f"{feature.value}_enabled"))


def require_feature(session: Session, business_id: int, feature: Feature) -> None:
    """403 `plan_required` when the business's plan does not include `feature`."""
    if not has_feature(_plan_of(session, business_id), feature):
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The plan does not include {feature.value}",
            code=ErrorCode.PLAN_REQUIRED,
        )


def history_since(session: Session, business_id: int) -> datetime | None:
    """Oldest moment the history may show, or None for all of it.

    Filters the movement list, its export and their totals; never a balance.
    """
    days = _plan_of(session, business_id).history_days
    return None if days is None else utc_now() - timedelta(days=days)


# --- Summary and assignment ---------------------------------------------------


def summary(session: Session, business_id: int) -> PlanSummaryResponse:
    """Effective plan, trial and usage against the limits of the business."""
    # The business always exists: the caller got its id from a token or a lookup.
    business = session.get(Business, business_id)
    plan = effective_plan(session, business)
    assigned = session.get(Plan, business.plan_id) if business.plan_id is not None else None
    used = usage(session, business.id)
    return PlanSummaryResponse(
        plan=PlanResponse.model_validate(plan),
        assigned_plan_key=assigned.key if assigned else None,
        trial_ends_at=as_utc(business.trial_ends_at) if business.trial_ends_at else None,
        trial_active=trial_active(business),
        unit_price_cents=business.unit_price_cents,
        usage=PlanUsageResponse(
            customers=UsageItemResponse(
                used=used[Capacity.CUSTOMERS], limit=limit_of(plan, Capacity.CUSTOMERS)
            ),
            users=UsageItemResponse(
                used=used[Capacity.USERS], limit=limit_of(plan, Capacity.USERS)
            ),
        ),
    )


def assign(
    session: Session, business: Business, plan_id: int, unit_price_cents: int | None = None
) -> None:
    """The platform sets a plan by hand (no payment gateway). Does not commit.

    Any plan of the catalog, hidden ones included. It ends a trial in progress:
    the plan is now contracted. The agreed price defaults to the plan's price.
    422 `plan_invalid` when the plan does not exist.
    """
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Plan not found",
            code=ErrorCode.PLAN_INVALID,
        )
    business.plan_id = plan.id
    business.trial_ends_at = None
    business.unit_price_cents = plan.price_cents if unit_price_cents is None else unit_price_cents
