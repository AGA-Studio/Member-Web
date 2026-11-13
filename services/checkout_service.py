"""Checkout at the counter: register a purchase and read its receipt (contract, section 5).

Every function receives the `business_id` from the token. A customer or a
purchase of another business is treated as nonexistent (404).

Rules:
- The arithmetic lives in `services/pricing_service.py` (discount first; points
  and cashback on the discounted base).
- Only an `active` card gets benefits. An expired or cancelled card is charged
  the full amount and earns nothing; the receipt says so with `card_status`.
- `use_cashback` spends at most the customer's balance and never more than the
  discounted base.
- The customer row is locked while the purchase is written (PostgreSQL
  `SELECT ... FOR UPDATE`), so two simultaneous charges cannot spend the same
  cashback twice.
- `Idempotency-Key`: the same key in the same business returns the purchase
  already created. The same key with a different customer, amount or concept
  is a 409 `idempotency_conflict`.
- A cashier can only read the receipts they registered; an admin, every
  receipt of the business.
"""

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from models.customer_model import Customer
from models.purchase_model import CardStatus, Purchase
from models.tier_model import Tier
from models.user_model import Role, User
from schemas.checkout_schema import (
    CheckoutCreate,
    CheckoutPreviewResponse,
    CustomerRefResponse,
    ReceiptResponse,
)
from schemas.customer_schema import TierSummaryResponse
from services import customer_service, pricing_service

# $1,000,000.00: far above any counter sale; protects the integer columns.
MAX_AMOUNT_CENTS = 100_000_000

_checkout_not_found = ApiError(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Checkout not found",
    code=ErrorCode.CHECKOUT_NOT_FOUND,
)
_customer_not_found = ApiError(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Customer not found",
    code=ErrorCode.CUSTOMER_NOT_FOUND,
)
_idempotency_conflict = ApiError(
    status_code=status.HTTP_409_CONFLICT,
    detail="Idempotency-Key already used for a different purchase",
    code=ErrorCode.IDEMPOTENCY_CONFLICT,
)


def _validate_amount(amount_cents: int) -> None:
    if not 0 < amount_cents <= MAX_AMOUNT_CENTS:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"amount_cents must be between 1 and {MAX_AMOUNT_CENTS}",
            code=ErrorCode.AMOUNT_INVALID,
        )


def _customer_row(
    session: Session, business_id: int, customer_id: int, *, lock: bool = False
) -> tuple[Customer, Tier]:
    query = customer_service.with_tier(business_id).where(Customer.id == customer_id)
    if lock:
        query = query.with_for_update(of=Customer)
    row = session.exec(query).first()
    if row is None:
        raise _customer_not_found
    return row


def _breakdown(
    session: Session, business_id: int, customer: Customer, tier: Tier, data: CheckoutCreate
) -> tuple[CardStatus, customer_service.Balance, pricing_service.Breakdown]:
    card_status = CardStatus(customer_service.customer_status(customer, customer_service.utc_now()))
    balance = customer_service.balance_of(session, business_id, customer.id)
    breakdown = pricing_service.calculate(
        data.amount_cents,
        discount_percent=tier.discount_percent,
        points_per_ten=tier.points_per_ten,
        cashback_percent=tier.cashback_percent,
        cashback_balance_cents=balance.cashback_cents,
        use_cashback=data.use_cashback,
        benefits_apply=card_status == CardStatus.ACTIVE,
    )
    return card_status, balance, breakdown


def to_receipt(purchase: Purchase, customer: Customer) -> ReceiptResponse:
    return ReceiptResponse(
        id=purchase.id,
        created_at=customer_service.as_utc(purchase.created_at),
        customer=CustomerRefResponse(
            id=customer.id, full_name=customer.full_name, code=customer.code
        ),
        level=TierSummaryResponse(
            id=purchase.tier_id, name=purchase.tier_name, finish=purchase.tier_finish
        ),
        card_status=purchase.card_status,
        concept=purchase.concept,
        amount_cents=purchase.amount_cents,
        discount_percent=purchase.discount_percent,
        discount_cents=purchase.discount_cents,
        cashback_used_cents=purchase.cashback_used_cents,
        total_cents=purchase.total_cents,
        points_earned=purchase.points_earned,
        cashback_earned_cents=purchase.cashback_earned_cents,
        points_balance_after=purchase.points_balance_after,
        cashback_balance_after_cents=purchase.cashback_balance_after_cents,
    )


def _receipt_of(session: Session, purchase: Purchase) -> ReceiptResponse:
    return to_receipt(purchase, session.get(Customer, purchase.customer_id))


# --- Preview ------------------------------------------------------------------


def preview(session: Session, business_id: int, data: CheckoutCreate) -> CheckoutPreviewResponse:
    """What `create` would charge, without saving anything."""
    _validate_amount(data.amount_cents)
    customer, tier = _customer_row(session, business_id, data.customer_id)
    card_status, _, b = _breakdown(session, business_id, customer, tier, data)
    return CheckoutPreviewResponse(
        card_status=card_status,
        amount_cents=data.amount_cents,
        discount_percent=b.discount_percent,
        discount_cents=b.discount_cents,
        cashback_used_cents=b.cashback_used_cents,
        total_cents=b.total_cents,
        points_earned=b.points_earned,
        cashback_earned_cents=b.cashback_earned_cents,
    )


# --- Create -------------------------------------------------------------------


def _by_key(session: Session, business_id: int, key: str) -> Purchase | None:
    query = select(Purchase).where(
        Purchase.business_id == business_id, Purchase.idempotency_key == key
    )
    return session.exec(query).first()


def _replay(session: Session, existing: Purchase, data: CheckoutCreate) -> ReceiptResponse:
    same = (existing.customer_id, existing.amount_cents, existing.concept) == (
        data.customer_id,
        data.amount_cents,
        data.concept,
    )
    if not same:
        raise _idempotency_conflict
    return _receipt_of(session, existing)


def create(
    session: Session,
    business_id: int,
    cashier: User,
    data: CheckoutCreate,
    idempotency_key: str | None = None,
) -> tuple[ReceiptResponse, bool]:
    """Register the purchase. Returns the receipt and whether it was a replay."""
    _validate_amount(data.amount_cents)
    if idempotency_key is not None:
        existing = _by_key(session, business_id, idempotency_key)
        if existing is not None:
            return _replay(session, existing, data), True

    customer, tier = _customer_row(session, business_id, data.customer_id, lock=True)
    card_status, balance, b = _breakdown(session, business_id, customer, tier, data)
    purchase = Purchase(
        business_id=business_id,
        customer_id=customer.id,
        cashier_id=cashier.id,
        tier_id=tier.id,
        tier_name=tier.name,
        tier_finish=tier.finish,
        card_status=card_status,
        concept=data.concept,
        amount_cents=data.amount_cents,
        discount_percent=b.discount_percent,
        discount_cents=b.discount_cents,
        cashback_used_cents=b.cashback_used_cents,
        total_cents=b.total_cents,
        points_earned=b.points_earned,
        cashback_earned_cents=b.cashback_earned_cents,
        points_balance_after=balance.points + b.points_earned,
        cashback_balance_after_cents=(
            balance.cashback_cents - b.cashback_used_cents + b.cashback_earned_cents
        ),
        idempotency_key=idempotency_key,
    )
    session.add(purchase)
    try:
        session.commit()
    except IntegrityError:
        # Two requests with the same key raced past the lookup: the other one won.
        session.rollback()
        existing = _by_key(session, business_id, idempotency_key) if idempotency_key else None
        if existing is None:
            raise
        return _replay(session, existing, data), True
    session.refresh(purchase)
    return to_receipt(purchase, customer), False


# --- Read ---------------------------------------------------------------------


def get_receipt(
    session: Session, business_id: int, user: User, checkout_id: int
) -> ReceiptResponse:
    purchase = session.get(Purchase, checkout_id)
    if purchase is None or purchase.business_id != business_id:
        raise _checkout_not_found
    # A cashier only sees their own receipts; someone else's looks nonexistent.
    if user.role == Role.EMPLOYEE and purchase.cashier_id != user.id:
        raise _checkout_not_found
    return _receipt_of(session, purchase)
