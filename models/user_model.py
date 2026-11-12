"""System user: platform owner, business admin or cashier employee.

A business's customers are NOT users (they never log in).
"""

from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from models.enum_utils import enum_values


class Role(StrEnum):
    PLATFORM = "platform"  # Us: sees each business's status and usage, never its data.
    ADMIN = "admin"  # Administrator of one business.
    EMPLOYEE = "employee"  # Cashier of one business.


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    # Null only for the PLATFORM role; required for admin and employee.
    business_id: int | None = Field(default=None, foreign_key="businesses.id", index=True)
    name: str = Field(max_length=120)
    email: str = Field(max_length=255, unique=True, index=True)
    hashed_password: str
    role: Role = Field(
        default=Role.EMPLOYEE,
        sa_type=sa.Enum(Role, name="role", values_callable=enum_values),
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
