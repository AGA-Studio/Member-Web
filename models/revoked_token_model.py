"""Revoked access tokens (H2: logout invalidates the token).

A JWT cannot be "deleted": it stays valid until `exp`. On logout its `jti` is
stored here and every request checks this table. Rows are useless once the token
would have expired anyway, so they are purged after `expires_at`.

Not business data: it has no business_id.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class RevokedToken(SQLModel, table=True):
    __tablename__ = "revoked_tokens"

    jti: str = Field(primary_key=True, max_length=64)
    expires_at: datetime = Field(index=True)
    revoked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
