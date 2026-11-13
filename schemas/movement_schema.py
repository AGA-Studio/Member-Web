"""Output DTOs for the movement history (API contract, section 6).

A movement is a purchase seen from the history: same id as its receipt. The
purchase is the only movement type of the MVP. There is no register (decision
6): each movement carries the cashier who charged it instead.
"""

from datetime import datetime

from pydantic import BaseModel

from models.purchase_model import CardStatus
from schemas.checkout_schema import CustomerRefResponse
from schemas.pagination_schema import PageResponse


class MovementResponse(BaseModel):
    id: int
    created_at: datetime
    customer: CustomerRefResponse
    cashier_name: str
    card_status: CardStatus
    concept: str | None
    amount_cents: int
    discount_percent: float
    discount_cents: int
    cashback_used_cents: int
    total_cents: int
    points_delta: int
    cashback_earned_cents: int


class MovementSummaryResponse(BaseModel):
    """Totals of the whole filtered set, not just the page."""

    count: int
    collected_cents: int
    discount_cents: int
    cashback_used_cents: int


class MovementPageResponse(PageResponse[MovementResponse]):
    summary: MovementSummaryResponse
