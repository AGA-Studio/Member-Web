"""Input and output DTOs for customers (API contract, section 3).

The frontend sees a customer and their card as one resource. `business_id`
never comes in: it is taken from the token.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from models.membership_payment_model import PaymentMethod
from models.tier_model import TierFinish
from schemas.validators import PersonName

PHONE_MAX_LENGTH = 30


class CustomerStatus(StrEnum):
    """Computed, never stored. `cancelled` wins over everything."""

    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class CustomerStatusFilter(StrEnum):
    """Filter of `/customer/list`. `expiring` = active and expiring soon."""

    ACTIVE = "active"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def _clean_phone(value: str) -> str:
    return " ".join(value.split())


Phone = Annotated[
    str,
    Field(
        min_length=7,
        max_length=PHONE_MAX_LENGTH,
        pattern=r"^\+?[0-9][0-9 ()\-]*$",
        examples=["664 123 4567"],
    ),
    AfterValidator(_clean_phone),
]


class CustomerCreate(BaseModel):
    """Without `level_id` the customer gets the business's cheapest tier.

    `send_card_email` (default true) emails the customer the link to their card.
    The first payment is recorded with `payment_method`; `amount_cents` defaults to
    the tier's price, and 0 records no payment.
    """

    full_name: PersonName
    email: EmailStr
    phone: Phone | None = None
    level_id: int | None = None
    send_card_email: bool = True
    payment_method: PaymentMethod = PaymentMethod.CASH
    amount_cents: int | None = None


class CustomerRenew(BaseModel):
    """Renewal at the counter. `level_id` changes the tier at the same time.

    `amount_cents` defaults to the price of the (new) tier; 0 records no payment.
    """

    level_id: int | None = None
    payment_method: PaymentMethod = PaymentMethod.CASH
    amount_cents: int | None = None


class CustomerUpdate(BaseModel):
    """Every field is optional. `level_id` changes the tier (paid at the counter)."""

    full_name: PersonName | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    level_id: int | None = None


class TierSummaryResponse(BaseModel):
    id: int
    name: str
    finish: TierFinish


class BenefitsResponse(BaseModel):
    """Benefits of the customer's current tier, so the checkout needs no extra call."""

    discount_percent: float
    points_per_ten: int
    cashback_percent: float


class CustomerResponse(BaseModel):
    id: int
    code: str
    full_name: str
    email: EmailStr
    phone: str | None
    level: TierSummaryResponse
    status: CustomerStatus
    expiring_soon: bool
    issued_at: datetime
    valid_until: datetime
    points_balance: int
    cashback_balance_cents: int
    benefits: BenefitsResponse
    last_purchase_at: datetime | None


class CustomerSummaryResponse(BaseModel):
    """Counters for the Membresías tabs. `active` includes the expiring ones."""

    all: int
    active: int
    expiring: int
    expired: int
    cancelled: int
