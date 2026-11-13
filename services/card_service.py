"""Delivery of the digital card: secret link and public card (contract, section 13).

Rules:
- The token is `secrets.token_urlsafe(32)`; only its SHA-256 is stored
  (`card_deliveries.token_hash`). It cannot be derived from the code or the id.
- One active link per customer: creating a link revokes the previous one.
- The link lives as long as the card (DECISIÓN 10): `expires_at` is the card's
  `valid_until`. Unknown, revoked, expired, cancelled, or of a suspended
  business: always the same 404 `card_link_not_found`.
- No link for a cancelled (409 `customer_cancelled`) or expired (409
  `customer_expired`) card: it would never open.
"""

import hashlib
import secrets
from datetime import datetime

from fastapi import status
from sqlmodel import Session, select

from core.config import settings
from core.errors import ApiError, ErrorCode
from models.business_model import Business, BusinessStatus
from models.card_delivery_model import CardDelivery
from models.customer_model import Customer
from models.tier_model import Tier
from schemas.card_schema import (
    CardLinkResponse,
    PublicBusinessResponse,
    PublicCardResponse,
    PublicTierResponse,
    WalletAvailabilityResponse,
)
from schemas.customer_schema import CustomerStatus
from services.customer_service import as_utc, customer_status, utc_now

TOKEN_BYTES = 32
# token_urlsafe(32) is 43 characters; anything far longer is not a token.
TOKEN_MAX_LENGTH = 128

# Public answers must never be cached (they carry a person's card).
NO_STORE = {"Cache-Control": "no-store"}


def _error(status_code: int, detail: str, code: ErrorCode) -> ApiError:
    return ApiError(status_code=status_code, detail=detail, code=code)


def _link_not_found() -> ApiError:
    return ApiError(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Card link not found",
        code=ErrorCode.CARD_LINK_NOT_FOUND,
        headers=NO_STORE,
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def card_url(token: str) -> str:
    return f"{settings.frontend_public_url.rstrip('/')}/tarjeta/{token}"


# --- Panel (admin) ------------------------------------------------------------


def _load(session: Session, business_id: int, customer_id: int) -> tuple[Customer, Business]:
    row = session.exec(
        select(Customer, Business)
        .join(Business, Customer.business_id == Business.id)
        .where(Customer.business_id == business_id, Customer.id == customer_id)
    ).first()
    if row is None:
        raise _error(status.HTTP_404_NOT_FOUND, "Customer not found", ErrorCode.CUSTOMER_NOT_FOUND)
    return row


def _ensure_deliverable(customer: Customer, now: datetime) -> None:
    match customer_status(customer, now):
        case CustomerStatus.CANCELLED:
            raise _error(
                status.HTTP_409_CONFLICT, "Card is cancelled", ErrorCode.CUSTOMER_CANCELLED
            )
        case CustomerStatus.EXPIRED:
            raise _error(status.HTTP_409_CONFLICT, "Card is expired", ErrorCode.CUSTOMER_EXPIRED)


def new_link(session: Session, customer: Customer, now: datetime) -> tuple[str, CardDelivery]:
    """Revoke the active link (if any) and add a new one. Does not commit."""
    active = session.exec(
        select(CardDelivery).where(
            CardDelivery.business_id == customer.business_id,
            CardDelivery.customer_id == customer.id,
            CardDelivery.revoked_at.is_(None),  # type: ignore[union-attr]
        )
    ).all()
    for delivery in active:
        delivery.revoked_at = now
        session.add(delivery)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    delivery = CardDelivery(
        business_id=customer.business_id,
        customer_id=customer.id,
        token_hash=hash_token(token),
        created_at=now,
    )
    session.add(delivery)
    return token, delivery


def create_link(session: Session, business_id: int, customer_id: int) -> CardLinkResponse:
    """New link for "Copiar enlace". The previous one stops working."""
    customer, _ = _load(session, business_id, customer_id)
    now = utc_now()
    _ensure_deliverable(customer, now)
    token, _ = new_link(session, customer, now)
    session.commit()
    return CardLinkResponse(url=card_url(token), expires_at=as_utc(customer.valid_until))


# --- Public (no session) ------------------------------------------------------


def _resolve(session: Session, token: str) -> tuple[Customer, Tier, Business]:
    """The card behind a valid link, or the one 404 for every other case."""
    if not token or len(token) > TOKEN_MAX_LENGTH:
        raise _link_not_found()
    row = session.exec(
        select(Customer, Tier, Business)
        .join(CardDelivery, CardDelivery.customer_id == Customer.id)
        .join(Tier, Customer.tier_id == Tier.id)
        .join(Business, Customer.business_id == Business.id)
        .where(
            CardDelivery.token_hash == hash_token(token),
            CardDelivery.revoked_at.is_(None),  # type: ignore[union-attr]
            CardDelivery.business_id == Customer.business_id,
        )
    ).first()
    if row is None:
        raise _link_not_found()
    customer, tier, business = row
    if business.status == BusinessStatus.SUSPENDED:
        raise _link_not_found()
    if customer_status(customer, utc_now()) != CustomerStatus.ACTIVE:
        raise _link_not_found()
    return customer, tier, business


def public_card(session: Session, token: str) -> PublicCardResponse:
    customer, tier, business = _resolve(session, token)
    return PublicCardResponse(
        business=PublicBusinessResponse(name=business.name, logo_url=business.logo_url),
        full_name=customer.full_name,
        code=customer.code,
        level=PublicTierResponse(name=tier.name, finish=tier.finish),
        status=CustomerStatus.ACTIVE,
        valid_until=as_utc(customer.valid_until),
        # Google Wallet is not available yet: the frontend hides the button.
        wallet=WalletAvailabilityResponse(google=False),
    )
