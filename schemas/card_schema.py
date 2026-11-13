"""DTOs for the digital card delivery (API contract, section 13).

The public card (`PublicCardResponse`) carries only what is needed to draw the
card: no email, phone, points, cashback or numeric ids (DECISIÓN 11).
"""

from datetime import datetime

from pydantic import BaseModel

from models.tier_model import TierFinish
from schemas.customer_schema import CustomerStatus


class CardLinkResponse(BaseModel):
    """`expires_at` is the card's `valid_until`: the link lives as long as the card."""

    url: str
    expires_at: datetime


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
