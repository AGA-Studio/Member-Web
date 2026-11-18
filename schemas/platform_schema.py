"""Input and output DTOs for the platform owner (API contract, section 7).

The platform sees each business's status and usage, never its customers' data.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from models.business_model import BusinessStatus


class PlatformBusinessUpdate(BaseModel):
    """What the platform owner may change in a business: only its status.

    `trial` is not accepted: a business starts there, and how it leaves it depends
    on the open decisions about sign-up and plans (wiki, Decisiones por validar).
    """

    status: Literal[BusinessStatus.ACTIVE, BusinessStatus.SUSPENDED]


class PlatformBusinessResponse(BaseModel):
    id: int
    name: str
    # Same rule as `business.logo_url` in /auth/me: signed URL that expires, or null.
    logo_url: str | None = None
    status: BusinessStatus
    customers_count: int
    created_at: datetime


class PlatformSummaryResponse(BaseModel):
    """Totals for the platform dashboard: businesses by status and overall usage.

    Only counts, like the list: no customer, user or purchase data.
    """

    all: int
    trial: int
    active: int
    suspended: int
    # Cards that are not cancelled, across every business (same rule as the list).
    customers_count: int
    # Active users (admin and employee) across every business; the platform is not counted.
    users_count: int


class PlatformBusinessDetailResponse(PlatformBusinessResponse):
    """One business: the list item plus its configuration and usage. Still no customer data."""

    validity_months: int
    # Active users (admin and employee) of the business; inactive ones don't count.
    users_count: int
