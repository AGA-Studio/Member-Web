"""Card email: each attempt to email a customer their card link.

Only used to limit how often a customer gets the email (one per minute, five per
hour). Failed attempts count too, so a broken provider is not hammered.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class CardEmail(SQLModel, table=True):
    __tablename__ = "card_emails"

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="businesses.id", index=True)
    customer_id: int = Field(foreign_key="customers.id", index=True)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
