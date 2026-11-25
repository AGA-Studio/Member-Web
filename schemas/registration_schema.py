"""DTOs for the public business sign-up (issue #69).

The same field rules as the rest of the API: the business name of
`BusinessUpdate`, `PersonName` for the admin and the password of `UserCreate`.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.business_schema import NAME_MAX_LENGTH, NAME_MIN_LENGTH
from schemas.validators import PersonName


class RegistrationCreate(BaseModel):
    business_name: Annotated[str, Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)]
    admin_name: PersonName
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # A plan of `GET /plan/list`; left out, the default (free) plan.
    plan_id: int | None = None

    @field_validator("business_name", mode="before")
    @classmethod
    def collapse_spaces(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value


class RegistrationResponse(BaseModel):
    business_id: int
    name: str
    email: EmailStr
    plan: str  # Name of the plan the business got.
    plan_key: str
    # End of the free trial of the chosen plan; null when it has none.
    trial_ends_at: datetime | None
