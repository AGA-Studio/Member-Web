"""Failed login attempts per email (H4: brute-force protection).

One row per email with recent failures. A successful login deletes it; rows whose
last failure is older than the lockout window are purged.

Not business data: it has no business_id. It also tracks emails that do not
exist, so the API behaves the same for every email and does not reveal which
accounts exist.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel


class LoginAttempt(SQLModel, table=True):
    __tablename__ = "login_attempts"

    email: str = Field(primary_key=True, max_length=255)
    failed_count: int = Field(default=0)
    last_failed_at: datetime = Field(index=True)
    locked_until: datetime | None = Field(default=None)
