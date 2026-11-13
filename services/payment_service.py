"""Membership payments (contract, section 9, DECISIÓN 9).

A payment is recorded when a membership is created and when it is renewed. It
is added to the caller's transaction (no commit here), so the card and its
payment are saved together or not at all.

Rules:
- The amount is the tier's `price_cents` unless the admin sends `amount_cents`.
- 0 records nothing (free tier, or a membership given away); a negative amount
  or one above `MAX_AMOUNT_CENTS` is 422 `amount_invalid`.
"""

from datetime import datetime

from fastapi import status
from sqlmodel import Session

from core.errors import ApiError, ErrorCode
from models.customer_model import Customer
from models.membership_payment_model import MembershipPayment, PaymentKind, PaymentMethod
from models.tier_model import Tier

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
