"""Purchase: one charge at the counter. It is also the receipt and the movement.

The points and cashback balances of a customer are never stored on the
customer: they are the sum of these rows (`points_earned`, `cashback_earned_cents`
minus `cashback_used_cents`).

Each row keeps a snapshot of what was applied (tier name and finish, discount
percent, card status), so editing the tier later does not change old receipts.
`points_balance_after` and `cashback_balance_after_cents` are the balances right
after this purchase, as printed on the receipt.

`idempotency_key` (optional `Idempotency-Key` header) is unique per business: a
retried request returns the purchase already created instead of charging twice.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from models.enum_utils import enum_values
from models.tier_model import TierFinish


class CardStatus(StrEnum):
    """Status of the card at the moment of the purchase."""

    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Purchase(SQLModel, table=True):
    __tablename__ = "purchases"
    __table_args__ = (
        sa.UniqueConstraint(
            "business_id", "idempotency_key", name="uq_purchases_business_idempotency_key"
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_purchases_amount_cents"),
        sa.CheckConstraint("cashback_used_cents >= 0", name="ck_purchases_cashback_used_cents"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="businesses.id", index=True)
    customer_id: int = Field(foreign_key="customers.id", index=True)
    cashier_id: int = Field(foreign_key="users.id", index=True)
    tier_id: int = Field(foreign_key="tiers.id")
    tier_name: str = Field(max_length=60)
    tier_finish: TierFinish = Field(
        sa_type=sa.Enum(TierFinish, name="tierfinish", values_callable=enum_values),
    )
    card_status: CardStatus = Field(
        sa_type=sa.Enum(CardStatus, name="cardstatus", values_callable=enum_values),
    )
    concept: str | None = Field(default=None, max_length=120)
    amount_cents: int
    discount_percent: Decimal = Field(max_digits=5, decimal_places=2)
    discount_cents: int
    cashback_used_cents: int
    total_cents: int
    points_earned: int
    cashback_earned_cents: int
    points_balance_after: int
    cashback_balance_after_cents: int
    idempotency_key: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
