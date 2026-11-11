"""Business: each company that subscribes to Member+ (one tenant of the SaaS)."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


class BusinessStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Business(SQLModel, table=True):
    __tablename__ = "businesses"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    logo_url: str | None = Field(default=None, max_length=500)
    status: BusinessStatus = Field(default=BusinessStatus.TRIAL)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
