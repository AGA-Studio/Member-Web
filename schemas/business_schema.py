"""Input and output DTOs for businesses."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.business_model import BusinessStatus
from schemas.validators import HexColor

# Bounds of `validity_months` (wiki, "¿Vigencia y precio?": configurable per business).
VALIDITY_MONTHS_MIN = 1
VALIDITY_MONTHS_MAX = 60
NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 120


class BusinessUpdate(BaseModel):
    """Business settings the admin edits (screen 13). Only the fields sent change.

    `validity_months` applies to cards created or renewed afterwards; cards already
    issued keep their `valid_until`.

    `primary_color` is the exception to "null keeps the value": the color is
    optional, so an explicit `null` removes it and the business goes back to
    Member+ blue. Leaving the field out keeps it.
    """

    name: Annotated[str, Field(min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)] | None = (
        None
    )
    validity_months: (
        Annotated[int, Field(ge=VALIDITY_MONTHS_MIN, le=VALIDITY_MONTHS_MAX, strict=True)] | None
    ) = None
    primary_color: HexColor | None = None

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
    # "#rrggbb", or None for Member+ blue. `primary_foreground` is the text color
    # that stays readable on it ("#ffffff" or "#000000"); None without a color.
    primary_color: str | None
    primary_foreground: str | None = None
