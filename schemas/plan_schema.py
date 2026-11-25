"""Output DTOs for plans. The catalog is read-only through the API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlanResponse(BaseModel):
    """One plan of the catalog. A limit in `null` is unlimited."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    price_cents: int
    max_customers: int | None
    max_users: int | None
    max_devices: int | None
    history_days: int | None
    images_enabled: bool
    exports_enabled: bool
    ai_enabled: bool
    ai_messages_month: int
    trial_days: int
    is_default: bool


class UsageItemResponse(BaseModel):
    """How much of one capacity is in use. `limit` in `null` is unlimited."""

    used: int
    limit: int | None


class PlanUsageResponse(BaseModel):
    customers: UsageItemResponse
    users: UsageItemResponse


class PlanSummaryResponse(BaseModel):
    """The plan a business has right now and how much of it it uses.

    `plan` is the effective plan (an ended trial is the default plan);
    `assigned_plan_key` is the one stored in the business, which may differ.
    """

    plan: PlanResponse
    assigned_plan_key: str | None
    trial_ends_at: datetime | None
    trial_active: bool
    # Agreed monthly price of the business; null when it never had a paid plan.
    unit_price_cents: int | None
    usage: PlanUsageResponse
