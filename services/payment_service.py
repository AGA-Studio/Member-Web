"""Membership payments (contract, section 9, DECISIÓN 9).

A payment is recorded when a membership is created and when it is renewed. It
is added to the caller's transaction (no commit here), so the card and its
payment are saved together or not at all.

Rules:
- The amount is the tier's `price_cents` unless the admin sends `amount_cents`.
- 0 records nothing (free tier, or a membership given away); a negative amount
  or one above `MAX_AMOUNT_CENTS` is 422 `amount_invalid`.
"""

import math
from datetime import datetime

from fastapi import status
from sqlalchemy import func
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from models.customer_model import Customer
from models.membership_payment_model import MembershipPayment, PaymentKind, PaymentMethod
from models.tier_model import Tier
from models.user_model import User
from schemas.pagination_schema import PageResponse
from schemas.payment_schema import MembershipPaymentResponse, PaymentTierResponse

MAX_AMOUNT_CENTS = 100_000_000  # $1,000,000.00, the same cap as the checkout


def resolve_amount(tier: Tier, amount_cents: int | None) -> int:
    amount = tier.price_cents if amount_cents is None else amount_cents
    if not 0 <= amount <= MAX_AMOUNT_CENTS:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"amount_cents must be between 0 and {MAX_AMOUNT_CENTS}",
            code=ErrorCode.AMOUNT_INVALID,
        )
    return amount


def record(
    session: Session,
    *,
    customer: Customer,
    tier: Tier,
    kind: PaymentKind,
    method: PaymentMethod,
    amount_cents: int,
    period_start: datetime,
    period_end: datetime,
    recorded_by: int,
) -> MembershipPayment | None:
    """Add the payment to the session (no commit). Nothing for an amount of 0."""
    if amount_cents == 0:
        return None
    payment = MembershipPayment(
        business_id=customer.business_id,
        customer_id=customer.id,
        tier_id=tier.id,
        tier_name=tier.name,
        kind=kind,
        method=method,
        amount_cents=amount_cents,
        period_start=period_start,
        period_end=period_end,
        recorded_by=recorded_by,
    )
    session.add(payment)
    return payment


def list_payments(
    session: Session, business_id: int, customer_id: int, *, page: int = 1, page_size: int = 8
) -> PageResponse[MembershipPaymentResponse]:
    """Payments of one customer, most recent first. 404 if the customer is not ours."""
    # customer_service imports this module, so the import goes here.
    from services.customer_service import as_utc, get_customer

    get_customer(session, business_id, customer_id)
    conditions = (
        MembershipPayment.business_id == business_id,
        MembershipPayment.customer_id == customer_id,
    )
    total = session.exec(
        select(func.count()).select_from(MembershipPayment).where(*conditions)
    ).one()
    page = min(page, max(1, math.ceil(total / page_size)))
    rows = session.exec(
        select(MembershipPayment, User.name)
        .join(User, MembershipPayment.recorded_by == User.id)
        .where(*conditions)
        .order_by(MembershipPayment.created_at.desc(), MembershipPayment.id.desc())  # type: ignore[attr-defined]
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageResponse[MembershipPaymentResponse](
        items=[
            MembershipPaymentResponse(
                id=payment.id,
                created_at=as_utc(payment.created_at),
                kind=payment.kind,
                method=payment.method,
                amount_cents=payment.amount_cents,
                level=PaymentTierResponse(id=payment.tier_id, name=payment.tier_name),
                period_start=as_utc(payment.period_start),
                period_end=as_utc(payment.period_end),
                recorded_by_name=name,
            )
            for payment, name in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
