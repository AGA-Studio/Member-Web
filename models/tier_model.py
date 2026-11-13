"""Tier: a membership level of one business (Bronce, Plata, Oro...).

Each business defines its own tiers; the seed only loads a starting template.
A customer's tier sets the benefits applied at checkout: discount first, then
points and cashback on the discounted total.

A customer moves up by paying for a better tier ("por cobro": more benefits,
higher price), not by accumulating points. Points are only a balance.

A benefit set to 0 means it is disabled for that tier (no extra flag).
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from models.enum_utils import enum_values


class TierFinish(StrEnum):
    """Visual finish of the card and badge. The tier name is free text."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    ONYX = "onyx"


class Tier(SQLModel, table=True):
    __tablename__ = "tiers"
    # Last line of defense; the service answers 422 `tier_invalid` before these fire.
    __table_args__ = (
        sa.CheckConstraint("price_cents >= 0", name="ck_tiers_price_cents"),
        sa.CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100", name="ck_tiers_discount_percent"
        ),
        sa.CheckConstraint("points_per_ten >= 0", name="ck_tiers_points_per_ten"),
        sa.CheckConstraint(
            "cashback_percent >= 0 AND cashback_percent <= 100", name="ck_tiers_cashback_percent"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="businesses.id", index=True)
    name: str = Field(max_length=60)
    finish: TierFinish = Field(
        sa_type=sa.Enum(TierFinish, name="tierfinish", values_callable=enum_values),
    )
    # Price of the membership at this tier, per validity period, in MXN cents. 0 = free.
    price_cents: int = Field(default=0)
    discount_percent: Decimal = Field(default=Decimal(0), max_digits=5, decimal_places=2)
    # Points earned per $10 (1000 cents) of the discounted total.
    points_per_ten: int = Field(default=0)
    cashback_percent: Decimal = Field(default=Decimal(0), max_digits=5, decimal_places=2)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
