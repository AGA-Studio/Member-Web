"""Input and output DTOs for users. They never expose `hashed_password`."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models.user_model import Role
from schemas.business_schema import BusinessSummaryResponse
from schemas.validators import PersonName
from services import storage_service


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
    # The column keeps the storage key; the API answers with a signed URL that
    # expires (or null), so a key never reaches the frontend.
    photo_url: str | None = None

    @field_validator("photo_url", mode="after")
    @classmethod
    def _sign_photo(cls, value: str | None) -> str | None:
        return storage_service.public_url(value)


class MeResponse(UserResponse):
    """`GET /auth/me`: the session user plus their business, for the frontend header.

    `business` is null for the platform owner, who has no business.
    """

    business: BusinessSummaryResponse | None
