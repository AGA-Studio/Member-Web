"""Input and output DTOs for the platform owner (API contract, section 7).

The platform sees each business's status and usage, never its customers' data.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from models.business_model import BusinessStatus
from schemas.plan_schema import PlanSummaryResponse


class PlatformBusinessUpdate(BaseModel):
    """What the platform owner may change in a business: status and plan.

    At least one field. `trial` is not accepted as status: a business starts
    there. `plan_id` assigns a plan by hand (there is no payment gateway) and
    ends a trial in progress; `unit_price_cents` is the agreed monthly price,
    by default the plan's price when a plan is assigned.
    """

    status: Literal[BusinessStatus.ACTIVE, BusinessStatus.SUSPENDED] | None = None
    plan_id: int | None = None
    unit_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def _something_to_change(self) -> PlatformBusinessUpdate:
        if self.status is None and self.plan_id is None and self.unit_price_cents is None:
            raise ValueError("Send status, plan_id or unit_price_cents")
        return self


class PlatformBusinessResponse(BaseModel):
    id: int
    name: str
    # Same rule as `business.logo_url` in /auth/me: signed URL that expires, or null.
    logo_url: str | None = None
    status: BusinessStatus
    customers_count: int
    # Effective plan: an ended trial shows the default plan.
    plan_key: str
    plan_name: str
    trial_ends_at: datetime | None
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
    plan: PlanSummaryResponse
