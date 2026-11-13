"""Delivery of the digital card: secret link, email and public card (contract, section 13).

Rules:
- The token is `secrets.token_urlsafe(32)`; only its SHA-256 is stored
  (`card_deliveries.token_hash`). It cannot be derived from the code or the id.
- One active link per customer: creating a link revokes the previous one. Since
  the token in clear is never stored, every email carries a new link, so
  sending again also revokes the link sent before.
- The link lives as long as the card (DECISIÓN 10): `expires_at` is the card's
  `valid_until`. Unknown, revoked, expired, cancelled, or of a suspended
  business: always the same 404 `card_link_not_found`.
- No link for a cancelled (409 `customer_cancelled`) or expired (409
  `customer_expired`) card: it would never open.
- Email limit per customer: one per minute and five per hour (429
  `card_email_rate_limited`, with `Retry-After`). Failed attempts count.
- Creating a customer sends the email by default (DECISIÓN 14); a failed email
  never fails the creation: the response says `sent`, `failed`, `pending` or
  `skipped`.
"""

import hashlib
import html
import math
import secrets
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

from fastapi import status
from sqlalchemy import func
from sqlmodel import Session, select

from core.config import settings
from core.errors import ApiError, ErrorCode
from models.business_model import Business, BusinessStatus
from models.card_delivery_model import CardDelivery
from models.card_email_model import CardEmail
from models.customer_model import Customer
from models.tier_model import Tier
from schemas.card_schema import (
    CardEmailResult,
    CardEmailSentResponse,
    CardEmailStatus,
    CardLinkResponse,
    CustomerCreatedResponse,
    GoogleWalletResponse,
    PublicBusinessResponse,
    PublicCardResponse,
    PublicTierResponse,
    WalletAvailabilityResponse,
)
from schemas.customer_schema import CustomerCreate, CustomerStatus
from services import customer_service, email_service, wallet_service
from services.customer_service import as_utc, customer_status, utc_now

TOKEN_BYTES = 32
# token_urlsafe(32) is 43 characters; anything far longer is not a token.
TOKEN_MAX_LENGTH = 128
EMAILS_PER_HOUR = 5
EMAIL_INTERVAL = timedelta(minutes=1)
EMAIL_WINDOW = timedelta(hours=1)

# Public answers must never be cached (they carry a person's card).
NO_STORE = {"Cache-Control": "no-store"}


def _error(status_code: int, detail: str, code: ErrorCode, **headers: str) -> ApiError:
    return ApiError(status_code=status_code, detail=detail, code=code, headers=headers or None)


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


def _check_email_limit(session: Session, customer: Customer, now: datetime) -> None:
    window_start = now - EMAIL_WINDOW
    count, first, last = session.exec(
        select(func.count(), func.min(CardEmail.sent_at), func.max(CardEmail.sent_at)).where(
            CardEmail.business_id == customer.business_id,
            CardEmail.customer_id == customer.id,
            CardEmail.sent_at > window_start,
        )
    ).one()
    wait: timedelta | None = None
    if last is not None and as_utc(last) > now - EMAIL_INTERVAL:
        wait = as_utc(last) + EMAIL_INTERVAL - now
    if count >= EMAILS_PER_HOUR:
        wait = max(wait or timedelta(0), as_utc(first) + EMAIL_WINDOW - now)
    if wait is not None:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Card email sent too recently",
            ErrorCode.CARD_EMAIL_RATE_LIMITED,
            **{"Retry-After": str(max(1, math.ceil(wait.total_seconds())))},
        )


def _one_line(text: str) -> str:
    return " ".join(text.split())


def card_email(business: Business, customer: Customer, url: str) -> EmailMessage:
    """The email of section 13.7: no card code, points or balance in it."""
    business_name = _one_line(business.name)
    message = EmailMessage()
    message["Subject"] = f"Tu tarjeta de {business_name}"
    message["From"] = formataddr((business_name, settings.mail_from))
    message["To"] = customer.email
    message.set_content(
        f"Hola, {customer.full_name}:\n\n"
        f"{business_name} te dio una tarjeta de membresía. "
        "Ábrela para guardarla en tu teléfono.\n\n"
        f"Ver mi tarjeta: {url}\n\n"
        "Si no esperabas este correo, puedes ignorarlo.\n"
    )
    name, place, link = (
        html.escape(customer.full_name),
        html.escape(business_name),
        html.escape(url),
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="es">
<body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.5;">
  <p>Hola, {name}:</p>
  <p>{place} te dio una tarjeta de membresía. Ábrela para guardarla en tu teléfono.</p>
  <p>
    <a href="{link}" style="display: inline-block; padding: 12px 20px; background: #111827;
       color: #ffffff; text-decoration: none; border-radius: 6px;">Ver mi tarjeta</a>
  </p>
  <p style="font-size: 13px; color: #4b5563;">Si el botón no abre, copia este enlace:<br>
    <a href="{link}">{link}</a></p>
  <p style="font-size: 13px; color: #4b5563;">Si no esperabas este correo, puedes ignorarlo.</p>
</body>
</html>
""",
        subtype="html",
    )
    return message


def _email_link(
    session: Session, customer: Customer, business: Business, now: datetime
) -> email_service.SendResult:
    """New link, record the attempt, commit, then send (outside the transaction)."""
    token, delivery = new_link(session, customer, now)
    delivery.last_sent_at = now
    session.add(CardEmail(business_id=customer.business_id, customer_id=customer.id, sent_at=now))
    session.commit()
    return email_service.deliver(card_email(business, customer, card_url(token)))


def send_link(session: Session, business_id: int, customer_id: int) -> CardEmailSentResponse:
    """Email the card link (a new one). 502 `email_failed` if the provider fails."""
    customer, business = _load(session, business_id, customer_id)
    now = utc_now()
    _ensure_deliverable(customer, now)
    _check_email_limit(session, customer, now)
    sent_to = customer.email
    if _email_link(session, customer, business, now) == email_service.SendResult.FAILED:
        raise _error(status.HTTP_502_BAD_GATEWAY, "Email provider failed", ErrorCode.EMAIL_FAILED)
    return CardEmailSentResponse(sent_to=sent_to, last_sent_at=now)


def create_customer(
    session: Session, business_id: int, data: CustomerCreate
) -> CustomerCreatedResponse:
    """`/customer/create` plus the card email. The customer is created even if it fails."""
    created = customer_service.create_customer(session, business_id, data)
    email_status = CardEmailStatus.SKIPPED
    if data.send_card_email:
        customer, business = _load(session, business_id, created.id)
        result = _email_link(session, customer, business, utc_now())
        email_status = CardEmailStatus(result.value)
    return CustomerCreatedResponse(
        **created.model_dump(), card_email=CardEmailResult(status=email_status)
    )


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
        wallet=WalletAvailabilityResponse(google=wallet_service.is_configured()),
    )


def google_wallet(session: Session, token: str) -> GoogleWalletResponse:
    customer, tier, business = _resolve(session, token)
    if not wallet_service.is_configured():
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Wallet is not configured",
            code=ErrorCode.WALLET_UNAVAILABLE,
            headers=NO_STORE,
        )
    url = wallet_service.save_url(business, customer, tier, as_utc(customer.valid_until), utc_now())
    return GoogleWalletResponse(save_url=url)
