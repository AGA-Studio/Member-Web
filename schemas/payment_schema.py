"""Output DTOs for membership payments (contract, section 9, DECISIÓN 9)."""

from datetime import datetime

from pydantic import BaseModel

from models.membership_payment_model import PaymentKind, PaymentMethod


class PaymentTierResponse(BaseModel):
    """The tier that was paid, as it was named then."""

    id: int
    name: str


class MembershipPaymentResponse(BaseModel):
    id: int
    created_at: datetime
    kind: PaymentKind
    method: PaymentMethod
    amount_cents: int
    level: PaymentTierResponse
    period_start: datetime
    period_end: datetime
    recorded_by_name: str
