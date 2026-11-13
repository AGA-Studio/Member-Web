"""Input and output DTOs for the checkout (API contract, section 5).

The cashier comes from the token and `business_id` too: neither is in the body.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from models.purchase_model import CardStatus
from schemas.customer_schema import TierSummaryResponse

CONCEPT_MAX_LENGTH = 120


def _clean_concept(value: object) -> object:
    """Collapse spaces; an empty concept is no concept."""
    if isinstance(value, str):
        return " ".join(value.split()) or None
    return value


# The length limit goes on `str` so a blank concept (cleaned to None) skips it.
Concept = Annotated[
    Annotated[str, Field(max_length=CONCEPT_MAX_LENGTH, examples=["Café y pan dulce"])] | None,
    BeforeValidator(_clean_concept),
]


class CheckoutCreate(BaseModel):
    """`amount_cents` must be greater than 0 (422 `amount_invalid` otherwise)."""

    customer_id: int
    amount_cents: int
    concept: Concept = None
    use_cashback: bool = False


class CustomerRefResponse(BaseModel):
    id: int
    full_name: str
    code: str


class CheckoutPreviewResponse(BaseModel):
    """The numbers `create` would store, without storing anything."""

    card_status: CardStatus
    amount_cents: int
    discount_percent: float
    discount_cents: int
    cashback_used_cents: int
    total_cents: int
    points_earned: int
    cashback_earned_cents: int


class ReceiptResponse(CheckoutPreviewResponse):
    """A purchase as printed. `level` and `discount_percent` are the ones applied then."""

    id: int
    created_at: datetime
    customer: CustomerRefResponse
    level: TierSummaryResponse
    concept: str | None
    points_balance_after: int
    cashback_balance_after_cents: int
