"""Input and output DTOs for tiers.

Ranges are checked in `services/tier_service.py`, not here, so an out-of-range
value answers 422 with `code: tier_invalid` (API contract, section 4.3) instead
of FastAPI's generic list of field errors.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from models.tier_model import TierFinish


class TierUpdate(BaseModel):
    """Every field is optional; only the ones sent change."""

    name: str | None = None
    finish: TierFinish | None = None
    price_cents: int | None = None
    discount_percent: Decimal | None = None
    points_per_ten: int | None = None
    cashback_percent: Decimal | None = None


class TierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    finish: TierFinish
    price_cents: int
    # Numbers in JSON (15.0), not the strings Pydantic uses for Decimal.
    discount_percent: float
    points_per_ten: int
    cashback_percent: float
    customers_count: int = 0
