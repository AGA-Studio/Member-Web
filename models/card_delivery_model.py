"""Card delivery: the secret link that opens a customer's digital card.

The link is `{FRONTEND_PUBLIC_URL}/tarjeta/<token>`. The token is 32 random bytes
and only its SHA-256 is stored here: the token in clear exists only in the email
and in the response that creates the link.

- One active link per customer: a new link revokes the previous one.
- The link has no expiry of its own: it lives as long as the card (`valid_until`
  of the customer). An expired or cancelled card does not open.
- `revoked_at` is set when a new link replaces it or the card is cancelled.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class CardDelivery(SQLModel, table=True):
    __tablename__ = "card_deliveries"
    __table_args__ = (sa.UniqueConstraint("token_hash", name="uq_card_deliveries_token_hash"),)

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="businesses.id", index=True)
    customer_id: int = Field(foreign_key="customers.id", index=True)
    # SHA-256 of the token, in hexadecimal.
    token_hash: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = Field(default=None)
    last_sent_at: datetime | None = Field(default=None)
