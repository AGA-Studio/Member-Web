"""Input and output DTOs for businesses."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.business_model import BusinessStatus

# Bounds of `validity_months` (wiki, "¿Vigencia y precio?": configurable per business).
VALIDITY_MONTHS_MIN = 1
VALIDITY_MONTHS_MAX = 60
NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 120


class BusinessUpdate(BaseModel):
    """Business settings the admin edits (screen 13). Only the fields sent change.

    `validity_months` applies to cards created or renewed afterwards; cards already
    issued keep their `valid_until`.
    """

    name: Annotated[str, Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)] | None = (
        None
    )
    validity_months: (
        Annotated[int, Field(ge=VALIDITY_MONTHS_MIN, le=VALIDITY_MONTHS_MAX, strict=True)] | None
    ) = None

    @field_validator("name", mode="before")
    @classmethod
    def collapse_spaces(cls, value: object) -> object:
        # "  Café   Aurora " -> "Café Aurora", then the length is checked on the result.
        return " ".join(value.split()) if isinstance(value, str) else value


class BusinessSummaryResponse(BaseModel):
    """What the frontend header and settings need. No usage data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    logo_url: str | None
    status: BusinessStatus
    validity_months: int
