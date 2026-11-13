"""Membership payment: what a customer paid for a period of their card.

Recorded when a membership is created and every time it is renewed. There is
no payment gateway: the admin records what was charged at the counter.

- `amount_cents` is the tier's `price_cents` by default; the admin can change it.
  A free tier (amount 0) records no payment, so the amount is always > 0.
- `tier_name` is a snapshot: renaming the tier later does not change old payments.
- `period_start` and `period_end` are the validity this payment bought.
"""

from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from models.enum_utils import enum_values


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    TRANSFER = "transfer"


class PaymentKind(StrEnum):
    NEW = "new"
    RENEWAL = "renewal"


class MembershipPayment(SQLModel, table=True):
    __tablename__ = "membership_payments"
    __table_args__ = (
        sa.CheckConstraint("amount_cents > 0", name="ck_membership_payments_amount_cents"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="businesses.id", index=True)
    customer_id: int = Field(foreign_key="customers.id", index=True)
    tier_id: int = Field(foreign_key="tiers.id")
    tier_name: str = Field(max_length=60)
    kind: PaymentKind = Field(
        sa_type=sa.Enum(PaymentKind, name="paymentkind", values_callable=enum_values),
    )
    method: PaymentMethod = Field(
        sa_type=sa.Enum(PaymentMethod, name="paymentmethod", values_callable=enum_values),
    )
    amount_cents: int
    period_start: datetime
    period_end: datetime
    recorded_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
