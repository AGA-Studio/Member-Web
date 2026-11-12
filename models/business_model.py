"""Business: each company that subscribes to Member+ (one tenant of the SaaS)."""

from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from models.enum_utils import enum_values


class BusinessStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Business(SQLModel, table=True):
    __tablename__ = "businesses"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    logo_url: str | None = Field(default=None, max_length=500)
    status: BusinessStatus = Field(
        default=BusinessStatus.TRIAL,
        sa_type=sa.Enum(BusinessStatus, name="businessstatus", values_callable=enum_values),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
