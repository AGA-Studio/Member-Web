"""Output DTOs for the platform owner (API contract, section 7).

The platform sees each business's status and usage, never its customers' data.
"""

from datetime import datetime

from pydantic import BaseModel

from models.business_model import BusinessStatus


class PlatformBusinessResponse(BaseModel):
    id: int
    name: str
    status: BusinessStatus
    customers_count: int
    created_at: datetime
