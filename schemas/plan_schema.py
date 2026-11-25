"""Output DTOs for plans. The catalog is read-only through the API."""

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
