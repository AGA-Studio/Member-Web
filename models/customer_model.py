"""Customer: a person with a membership card in one business.

The card is not a separate table: a customer IS their card (one per customer),
with a tier, a validity period and a status. Customers never log in.

- `code` is the short, typeable code printed on the card and carried by the QR
  (for example `MP-4F7K2`). Random, unique within the business.
- `status` is not stored: it is computed from `cancelled_at` and `valid_until`
  (see `services/customer_service.py`). Cancelling is irreversible.
- Points and cashback are not columns: they are computed from the movements.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class Customer(SQLModel, table=True):
    __tablename__ = "customers"
    __table_args__ = (
        sa.UniqueConstraint("business_id", "code", name="uq_customers_business_code"),
        sa.UniqueConstraint("business_id", "email", name="uq_customers_business_email"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="businesses.id", index=True)
    tier_id: int = Field(foreign_key="tiers.id", index=True)
    code: str = Field(max_length=16)
    full_name: str = Field(max_length=120)
    # Stored in lowercase, so the unique constraint ignores case.
    email: str = Field(max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    issued_at: datetime
    valid_until: datetime = Field(index=True)
    cancelled_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
