"""Plan: what a business's subscription includes (issue #70).

A global catalog, not data of a business: no `business_id`, the same rows for
every tenant. The business points at one with `businesses.plan_id`; what it can
use right now is the *effective* plan (`services/plan_service.effective_plan`),
which falls back to the default plan when a trial is over.

Limits are counts; `None` means unlimited. They only apply when creating
something (a customer, a user, a reader): nothing already created is ever
removed or switched off by a plan.
"""

from sqlmodel import Field, SQLModel


class Plan(SQLModel, table=True):
    __tablename__ = "plans"

    id: int | None = Field(default=None, primary_key=True)
    # Stable identifier for code and seeds (`free`, `counter`, `business`, `chain`).
    key: str = Field(max_length=32, unique=True)
    name: str = Field(max_length=60)
    # Monthly price in MXN cents. Charged by hand: there is no payment gateway.
    price_cents: int = Field(default=0)
    max_customers: int | None = Field(default=None)
    max_users: int | None = Field(default=None)
    max_devices: int | None = Field(default=None)
    # Days of history shown in the movement list, its export and the dashboard
    # totals. Never the points or cashback balance, which is always complete.
    history_days: int | None = Field(default=None)
    images_enabled: bool = Field(default=False)
    exports_enabled: bool = Field(default=False)
    ai_enabled: bool = Field(default=False)
    ai_messages_month: int = Field(default=0)
    # Days of this plan a new business gets for free, once (0 = no trial).
    trial_days: int = Field(default=0)
    # The plan of a business with none assigned or whose trial ended. Exactly one.
    is_default: bool = Field(default=False)
    # Offered in the public list and at sign-up; hidden plans are assigned by hand.
    is_public: bool = Field(default=True)
    sort_order: int = Field(default=0)
