"""Tiers of a business: listing and editing their benefits.

Every function receives the `business_id` from the token; a tier of another
business is treated as nonexistent (404).

A customer moves up by paying for a better tier (decision "por cobro"), so a tier
has a price and no points threshold.

Rules for an update (API contract, section 4.3):
- `price_cents` (per validity period) and `points_per_ten` are whole numbers >= 0.
- `discount_percent` and `cashback_percent` go from 0 to 100, at most 2 decimals.
- Changes only affect new purchases: past movements keep the values they used.
"""

from decimal import Decimal

from fastapi import HTTPException, status
from sqlmodel import Session, select

from core.errors import ApiError, ErrorCode
from models.tier_model import Tier
from schemas.tier_schema import TierResponse, TierUpdate

NAME_MAX_LENGTH = 60
MAX_PRICE_CENTS = 100_000_000  # $1,000,000.00; fits PostgreSQL's INTEGER with room to spare.
MAX_POINTS_PER_TEN = 1_000
PERCENT_MAX = Decimal(100)


def _invalid(detail: str) -> ApiError:
    return ApiError(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
        code=ErrorCode.TIER_INVALID,
    )


def _business_tiers(session: Session, business_id: int) -> list[Tier]:
    query = select(Tier).where(Tier.business_id == business_id).order_by(Tier.price_cents, Tier.id)
    return list(session.exec(query).all())


def _customers_count_by_tier(session: Session, business_id: int) -> dict[int, int]:
    """Customers with a non-cancelled card per tier.

    The customers module does not exist yet, so every tier has 0. When it lands,
    this becomes a single GROUP BY query (no query per tier).
    """
    return {}


def _to_response(tier: Tier, counts: dict[int, int]) -> TierResponse:
    response = TierResponse.model_validate(tier)
    response.customers_count = counts.get(tier.id, 0)
    return response


def list_tiers(session: Session, business_id: int) -> list[TierResponse]:
    counts = _customers_count_by_tier(session, business_id)
    return [_to_response(tier, counts) for tier in _business_tiers(session, business_id)]


def get_tier(session: Session, business_id: int, tier_id: int) -> Tier:
    tier = session.get(Tier, tier_id)
    # A tier from another business returns 404, same as if it didn't exist.
    if tier is None or tier.business_id != business_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    return tier


def _check_whole(value: int, field: str, maximum: int) -> None:
    if not 0 <= value <= maximum:
        raise _invalid(f"{field} must be between 0 and {maximum}")


def _check_percent(value: Decimal, field: str) -> None:
    if not value.is_finite() or not 0 <= value <= PERCENT_MAX:
        raise _invalid(f"{field} must be between 0 and 100")
    if value.normalize().as_tuple().exponent < -2:
        raise _invalid(f"{field} allows at most 2 decimals")


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        raise _invalid(f"name must have between 1 and {NAME_MAX_LENGTH} characters")
    return name


def update_tier(session: Session, business_id: int, tier_id: int, data: TierUpdate) -> TierResponse:
    tier = get_tier(session, business_id, tier_id)
    # null means "not sent": every column is required, so it can never be cleared.
    changes = data.model_dump(exclude_unset=True, exclude_none=True)

    if "name" in changes:
        changes["name"] = _clean_name(changes["name"])
    if "price_cents" in changes:
        _check_whole(changes["price_cents"], "price_cents", MAX_PRICE_CENTS)
    if "points_per_ten" in changes:
        _check_whole(changes["points_per_ten"], "points_per_ten", MAX_POINTS_PER_TEN)
    for field in ("discount_percent", "cashback_percent"):
        if field in changes:
            _check_percent(changes[field], field)

    for field, value in changes.items():
        setattr(tier, field, value)
    session.add(tier)
    session.commit()
    session.refresh(tier)
    return _to_response(tier, _customers_count_by_tier(session, business_id))
