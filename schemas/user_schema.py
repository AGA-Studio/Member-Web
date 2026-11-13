"""Input and output DTOs for users. They never expose `hashed_password`."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from models.user_model import Role
from schemas.business_schema import BusinessSummaryResponse
from schemas.validators import PersonName


class UserCreate(BaseModel):
    """`business_id` is not accepted: it comes from the creating admin's token."""

    name: PersonName
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.EMPLOYEE


class UserUpdate(BaseModel):
    name: PersonName | None = None
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int | None
    name: str
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime


class MeResponse(UserResponse):
    """`GET /auth/me`: the session user plus their business, for the frontend header.

    `business` is null for the platform owner, who has no business.
    """

    business: BusinessSummaryResponse | None
