"""Public business sign-up (issue #69; wiki, "Registro de negocios: decisión").

One request creates the business, its first admin, three empty tiers and its
plan, in a single transaction: either all of it is written or none of it.

Rules:
- Direct and without manual approval: the business is born `active`. What
  expires is the plan (a trial), never the access (`status`).
- The plan must be one the public list offers (`is_public`) and one a business
  can take by itself: free, or with a trial. A paid plan without a trial is
  asked for later and assigned by the platform owner by hand (there is no
  payment gateway), so here it is 422 `plan_invalid`.
- Three empty tiers (Básico, Plata, Oro): $0 and no benefits. A discount is a
  pricing decision of the business, not ours.
- No email verification in this version (open point of the team).
- Runs as the owner of the tables, without `rls.activate()`, like the login:
  there is no business to scope to until this creates it.
"""

from datetime import timedelta

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from core.security import hash_password
from models.business_model import Business, BusinessStatus
from models.plan_model import Plan
from models.tier_model import Tier, TierFinish
from models.user_model import Role, User
from schemas.registration_schema import RegistrationCreate, RegistrationResponse
from services import plan_service
from services.customer_service import utc_now

DEFAULT_TIERS = [
    ("Básico", TierFinish.BRONZE),
    ("Plata", TierFinish.SILVER),
    ("Oro", TierFinish.GOLD),
]

_email_taken = ApiError(
    status_code=status.HTTP_409_CONFLICT,
    detail="Email already in use",
    code=ErrorCode.EMAIL_TAKEN,
)
_plan_invalid = ApiError(
    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    detail="Plan not available for sign-up",
    code=ErrorCode.PLAN_INVALID,
)


def selectable(plan: Plan | None) -> bool:
    """A plan a new business can take by itself, without paying."""
    if plan is None or not plan.is_public:
        return False
    return plan.price_cents == 0 or plan.trial_days > 0


def _chosen_plan(session: Session, plan_id: int | None) -> Plan:
    plan = plan_service.default_plan(session) if plan_id is None else session.get(Plan, plan_id)
    if not selectable(plan):
        raise _plan_invalid
    return plan


def _ensure_email_available(session: Session, email: str) -> None:
    """Fast answer for the normal case; the unique index covers the race."""
    if session.exec(select(User).where(User.email == email)).first() is not None:
        raise _email_taken


def register(session: Session, data: RegistrationCreate) -> RegistrationResponse:
    email = data.email.lower()
    plan = _chosen_plan(session, data.plan_id)
    _ensure_email_available(session, email)

    trial_ends_at = utc_now() + timedelta(days=plan.trial_days) if plan.trial_days else None
    business = Business(
        name=data.business_name,
        status=BusinessStatus.ACTIVE,
        plan_id=plan.id,
        trial_ends_at=trial_ends_at,
        # Nothing is contracted yet: a trial or a free plan has no agreed price.
        unit_price_cents=None,
    )
    session.add(business)
    try:
        session.flush()
        session.add(
            User(
                business_id=business.id,
                name=data.admin_name,
                email=email,
                hashed_password=hash_password(data.password),
                role=Role.ADMIN,
            )
        )
        for name, finish in DEFAULT_TIERS:
            session.add(Tier(business_id=business.id, name=name, finish=finish, price_cents=0))
        session.commit()
    except IntegrityError:
        # Two sign-ups with the same email at once: the unique index stops the
        # second one, and nothing of it is left behind (H6).
        session.rollback()
        raise _email_taken from None
    session.refresh(business)
    return RegistrationResponse(
        business_id=business.id,
        name=business.name,
        email=email,
        plan=plan.name,
        plan_key=plan.key,
        trial_ends_at=trial_ends_at,
    )
