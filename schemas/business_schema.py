"""Output DTOs for businesses."""

from pydantic import BaseModel, ConfigDict

from models.business_model import BusinessStatus


class BusinessSummaryResponse(BaseModel):
    """What the frontend header needs: name, logo and status. No usage data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    logo_url: str | None
    status: BusinessStatus
