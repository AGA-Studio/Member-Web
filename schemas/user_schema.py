"""Input and output DTOs for users. They never expose `hashed_password`."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from models.user_model import Role


class UserCreate(BaseModel):
    """`business_id` is not accepted: it comes from the creating admin's token."""

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.EMPLOYEE


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
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
