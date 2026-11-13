"""DTOs for the digital card delivery (API contract, section 13).

The public card (`PublicCardResponse`) carries only what is needed to draw the
card: no email, phone, points, cashback or numeric ids (DECISIÓN 11).
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr

from models.tier_model import TierFinish
from schemas.customer_schema import CustomerResponse, CustomerStatus


class CardLinkResponse(BaseModel):
    """`expires_at` is the card's `valid_until`: the link lives as long as the card."""

    url: str
    expires_at: datetime


class CardEmailSentResponse(BaseModel):
    sent_to: EmailStr
    last_sent_at: datetime


class CardEmailStatus(StrEnum):
    """`pending`: the provider did not answer in time and the send goes on in the background."""

    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"
    SKIPPED = "skipped"


class CardEmailResult(BaseModel):
    status: CardEmailStatus


class CustomerCreatedResponse(CustomerResponse):
    """`/customer/create`: the customer plus what happened with the card email."""

    card_email: CardEmailResult


class PublicBusinessResponse(BaseModel):
    name: str
    logo_url: str | None


class PublicTierResponse(BaseModel):
    name: str
    finish: TierFinish


class WalletAvailabilityResponse(BaseModel):
    google: bool


class PublicCardResponse(BaseModel):
    business: PublicBusinessResponse
    full_name: str
    code: str
    level: PublicTierResponse
    status: CustomerStatus
    valid_until: datetime
    wallet: WalletAvailabilityResponse
