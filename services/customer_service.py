"""Customers of a business and their card (API contract, section 3).

Every function receives the `business_id` from the token; a customer of another
business is treated as nonexistent (404 `customer_not_found`).

Rules:
- The card code is `MP-` plus 5 random characters from an alphabet without the
  look-alikes 0/O and 1/I/L (for example `MP-4F7K2`), unique within the business.
  Lookups ignore spaces and case.
- The card is valid for the business's `validity_months` (12 by default) from
  the day it is issued (DECISIÓN 9). Creating it records the first payment.
- Status is computed: `cancelled` if it was cancelled (irreversible), else
  `expired` once `valid_until` passed, else `active`. `expiring_soon` marks
  active cards that expire within `EXPIRING_DAYS`.
- A customer moves to another tier when the admin assigns it (tiers are paid,
  not earned with points).
- Points and cashback balances are never stored on the customer: they are the
  sum of the customer's purchases (`balances`), in one query per page.
"""

import calendar
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import ColumnElement, and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from models.business_model import Business
from models.card_delivery_model import CardDelivery
from models.customer_model import Customer
from models.membership_payment_model import PaymentKind
from models.purchase_model import Purchase
from models.tier_model import Tier
from schemas.customer_schema import (
    BenefitsResponse,
    CustomerCreate,
    CustomerResponse,
    CustomerStatus,
    CustomerStatusFilter,
    CustomerSummaryResponse,
    CustomerUpdate,
    TierSummaryResponse,
)
from schemas.pagination_schema import PageResponse
from services import payment_service

CODE_PREFIX = "MP-"
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 5
CODE_ATTEMPTS = 10
VALIDITY_MONTHS = 12
EXPIRING_DAYS = 30

_not_found = ApiError(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Customer not found",
    code=ErrorCode.CUSTOMER_NOT_FOUND,
)
_email_taken = ApiError(
    status_code=status.HTTP_409_CONFLICT,
    detail="Email already in use",
    code=ErrorCode.EMAIL_TAKEN,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def add_months(moment: datetime, months: int) -> datetime:
    """Same day `months` later; the 31st becomes the last day of a shorter month."""
    month_index = moment.month - 1 + months
    year, month = moment.year + month_index // 12, month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def normalize_code(code: str) -> str:
    return "".join(code.split()).upper()


def generate_code() -> str:
    return CODE_PREFIX + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


# --- Status -------------------------------------------------------------------


def as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def customer_status(customer: Customer, now: datetime) -> CustomerStatus:
    if customer.cancelled_at is not None:
        return CustomerStatus.CANCELLED
    if as_utc(customer.valid_until) <= now:
        return CustomerStatus.EXPIRED
    return CustomerStatus.ACTIVE


def is_expiring_soon(customer: Customer, now: datetime) -> bool:
    return customer_status(customer, now) == CustomerStatus.ACTIVE and as_utc(
        customer.valid_until
    ) <= now + timedelta(days=EXPIRING_DAYS)


def _status_condition(wanted: CustomerStatusFilter, now: datetime) -> ColumnElement[bool]:
    not_cancelled = Customer.cancelled_at.is_(None)  # type: ignore[union-attr]
    soon = now + timedelta(days=EXPIRING_DAYS)
    match wanted:
        case CustomerStatusFilter.CANCELLED:
            return Customer.cancelled_at.is_not(None)  # type: ignore[union-attr]
        case CustomerStatusFilter.EXPIRED:
            return and_(not_cancelled, Customer.valid_until <= now)
        case CustomerStatusFilter.EXPIRING:
            return and_(not_cancelled, Customer.valid_until > now, Customer.valid_until <= soon)
        case CustomerStatusFilter.ACTIVE:
            return and_(not_cancelled, Customer.valid_until > now)


# --- Balances -----------------------------------------------------------------


@dataclass(frozen=True)
class Balance:
    points: int = 0
    cashback_cents: int = 0
    last_purchase_at: datetime | None = None


NO_BALANCE = Balance()


def balances(session: Session, business_id: int, customer_ids: list[int]) -> dict[int, Balance]:
    """Points and cashback of several customers, summed from their purchases in one query."""
    if not customer_ids:
        return {}
    query = (
        select(
            Purchase.customer_id,
            func.sum(Purchase.points_earned),
            func.sum(Purchase.cashback_earned_cents - Purchase.cashback_used_cents),
            func.max(Purchase.created_at),
        )
        .where(Purchase.business_id == business_id, Purchase.customer_id.in_(customer_ids))  # type: ignore[attr-defined]
        .group_by(Purchase.customer_id)
    )
    return {
        customer_id: Balance(int(points or 0), int(cashback or 0), last and as_utc(last))
        for customer_id, points, cashback, last in session.exec(query).all()
    }


def balance_of(session: Session, business_id: int, customer_id: int) -> Balance:
    return balances(session, business_id, [customer_id]).get(customer_id, NO_BALANCE)


# --- Responses ----------------------------------------------------------------


def to_response(
    customer: Customer,
    tier: Tier,
    now: datetime | None = None,
    balance: Balance = NO_BALANCE,
) -> CustomerResponse:
    now = now or utc_now()
    return CustomerResponse(
        id=customer.id,
        code=customer.code,
        full_name=customer.full_name,
        email=customer.email,
        phone=customer.phone,
        level=TierSummaryResponse(id=tier.id, name=tier.name, finish=tier.finish),
        status=customer_status(customer, now),
        expiring_soon=is_expiring_soon(customer, now),
        issued_at=as_utc(customer.issued_at),
        valid_until=as_utc(customer.valid_until),
        points_balance=balance.points,
        cashback_balance_cents=balance.cashback_cents,
        benefits=BenefitsResponse(
            discount_percent=tier.discount_percent,
            points_per_ten=tier.points_per_ten,
            cashback_percent=tier.cashback_percent,
        ),
        last_purchase_at=balance.last_purchase_at,
    )


def with_tier(business_id: int):
    return (
        select(Customer, Tier)
        .join(Tier, Customer.tier_id == Tier.id)
        .where(Customer.business_id == business_id)
    )


# --- Queries ------------------------------------------------------------------


def list_customers(
    session: Session,
    business_id: int,
    *,
    q: str | None = None,
    level_id: int | None = None,
    status_filter: CustomerStatusFilter | None = None,
    page: int = 1,
    page_size: int = 8,
) -> PageResponse[CustomerResponse]:
    now = utc_now()
    conditions: list[ColumnElement[bool]] = [Customer.business_id == business_id]
    if q and q.strip():
        needle = q.strip().lower()
        conditions.append(
            or_(
                func.lower(Customer.full_name).contains(needle, autoescape=True),
                func.lower(Customer.email).contains(needle, autoescape=True),
                func.lower(Customer.code).contains(needle, autoescape=True),
            )
        )
    if level_id is not None:
        conditions.append(Customer.tier_id == level_id)
    if status_filter is not None:
        conditions.append(_status_condition(status_filter, now))

    total = session.exec(select(func.count()).select_from(Customer).where(*conditions)).one()
    last_page = max(1, math.ceil(total / page_size))
    page = min(page, last_page)
    rows = session.exec(
        with_tier(business_id)
        .where(*conditions)
        .order_by(Customer.full_name, Customer.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    found = balances(session, business_id, [customer.id for customer, _ in rows])
    return PageResponse[CustomerResponse](
        items=[
            to_response(customer, tier, now, found.get(customer.id, NO_BALANCE))
            for customer, tier in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def summary(session: Session, business_id: int) -> CustomerSummaryResponse:
    now = utc_now()

    def count(*conditions: ColumnElement[bool]) -> int:
        query = (
            select(func.count())
            .select_from(Customer)
            .where(Customer.business_id == business_id, *conditions)
        )
        return session.exec(query).one()

    return CustomerSummaryResponse(
        all=count(),
        active=count(_status_condition(CustomerStatusFilter.ACTIVE, now)),
        expiring=count(_status_condition(CustomerStatusFilter.EXPIRING, now)),
        expired=count(_status_condition(CustomerStatusFilter.EXPIRED, now)),
        cancelled=count(_status_condition(CustomerStatusFilter.CANCELLED, now)),
    )


def counts_by_tier(session: Session, business_id: int) -> dict[int, int]:
    """Customers with a non-cancelled card per tier, in a single query."""
    query = (
        select(Customer.tier_id, func.count())
        .where(Customer.business_id == business_id, Customer.cancelled_at.is_(None))  # type: ignore[union-attr]
        .group_by(Customer.tier_id)
    )
    return dict(session.exec(query).all())


def _get_row(session: Session, business_id: int, customer_id: int) -> tuple[Customer, Tier]:
    row = session.exec(with_tier(business_id).where(Customer.id == customer_id)).first()
    if row is None:
        raise _not_found
    return row


def _response(
    session: Session, business_id: int, customer: Customer, tier: Tier
) -> CustomerResponse:
    return to_response(customer, tier, balance=balance_of(session, business_id, customer.id))


def get_customer(session: Session, business_id: int, customer_id: int) -> CustomerResponse:
    return _response(session, business_id, *_get_row(session, business_id, customer_id))


def lookup(session: Session, business_id: int, code: str) -> CustomerResponse:
    """Card read at the counter. Expired and cancelled cards are returned too."""
    row = session.exec(with_tier(business_id).where(Customer.code == normalize_code(code))).first()
    if row is None:
        raise _not_found
    return _response(session, business_id, *row)


# --- Changes ------------------------------------------------------------------


def _invalid_tier(detail: str) -> ApiError:
    return ApiError(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
        code=ErrorCode.TIER_INVALID,
    )


def _resolve_tier(session: Session, business_id: int, level_id: int | None) -> Tier:
    if level_id is None:
        cheapest = session.exec(
            select(Tier).where(Tier.business_id == business_id).order_by(Tier.price_cents, Tier.id)
        ).first()
        if cheapest is None:
            raise _invalid_tier("The business has no tiers yet")
        return cheapest
    tier = session.get(Tier, level_id)
    # A tier of another business is reported like a missing one.
    if tier is None or tier.business_id != business_id:
        raise _invalid_tier("Tier not found")
    return tier


def _email_in_use(session: Session, business_id: int, email: str, exclude_id: int | None) -> bool:
    query = select(Customer.id).where(Customer.business_id == business_id, Customer.email == email)
    if exclude_id is not None:
        query = query.where(Customer.id != exclude_id)
    return session.exec(query).first() is not None


def _code_in_use(session: Session, business_id: int, code: str) -> bool:
    query = select(Customer.id).where(Customer.business_id == business_id, Customer.code == code)
    return session.exec(query).first() is not None


def _new_code(session: Session, business_id: int) -> str:
    for _ in range(CODE_ATTEMPTS):
        code = generate_code()
        if not _code_in_use(session, business_id, code):
            return code
    # 31^5 ≈ 28.6 million codes per business: reaching this means something is broken.
    raise RuntimeError("Could not generate a unique card code")


def _commit(session: Session, customer: Customer) -> None:
    """Commit; a unique-email race that slipped past the check is a 409, not a 500."""
    session.add(customer)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise _email_taken from None
    session.refresh(customer)


def create_customer(
    session: Session, business_id: int, data: CustomerCreate, recorded_by: int
) -> CustomerResponse:
    """New customer and card, with its first payment in the same transaction."""
    email = data.email.lower()
    if _email_in_use(session, business_id, email, exclude_id=None):
        raise _email_taken
    tier = _resolve_tier(session, business_id, data.level_id)
    amount = payment_service.resolve_amount(tier, data.amount_cents)
    months = session.get(Business, business_id).validity_months
    issued_at = utc_now()
    customer = Customer(
        business_id=business_id,
        tier_id=tier.id,
        code=_new_code(session, business_id),
        full_name=data.full_name,
        email=email,
        phone=data.phone,
        issued_at=issued_at,
        valid_until=add_months(issued_at, months),
    )
    session.add(customer)
    try:
        session.flush()  # the payment needs the customer id
    except IntegrityError:
        session.rollback()
        raise _email_taken from None
    payment_service.record(
        session,
        customer=customer,
        tier=tier,
        kind=PaymentKind.NEW,
        method=data.payment_method,
        amount_cents=amount,
        period_start=issued_at,
        period_end=customer.valid_until,
        recorded_by=recorded_by,
    )
    _commit(session, customer)
    return to_response(customer, tier)


def update_customer(
    session: Session, business_id: int, customer_id: int, data: CustomerUpdate
) -> CustomerResponse:
    customer, tier = _get_row(session, business_id, customer_id)
    # null means "not sent" for the required columns; `phone` can be cleared.
    changes = data.model_dump(exclude_unset=True)
    for required in ("full_name", "email", "level_id"):
        if changes.get(required, "") is None:
            changes.pop(required)

    if "email" in changes:
        changes["email"] = changes["email"].lower()
        if _email_in_use(session, business_id, changes["email"], exclude_id=customer.id):
            raise _email_taken
    if "level_id" in changes:
        tier = _resolve_tier(session, business_id, changes.pop("level_id"))
        customer.tier_id = tier.id
    for field, value in changes.items():
        setattr(customer, field, value)
    _commit(session, customer)
    return _response(session, business_id, customer, tier)


def cancel_customer(session: Session, business_id: int, customer_id: int) -> CustomerResponse:
    """Irreversible, and it revokes the card link. Cancelling again changes nothing."""
    customer, tier = _get_row(session, business_id, customer_id)
    if customer.cancelled_at is None:
        now = utc_now()
        customer.cancelled_at = now
        links = session.exec(
            select(CardDelivery).where(
                CardDelivery.business_id == business_id,
                CardDelivery.customer_id == customer.id,
                CardDelivery.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        ).all()
        for link in links:
            link.revoked_at = now
            session.add(link)
        _commit(session, customer)
    return _response(session, business_id, customer, tier)
