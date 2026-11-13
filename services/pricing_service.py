"""Checkout arithmetic (API contract, section 5.1). Pure: no database.

All amounts are integer MXN cents. The frontend repeats this exact formula to
show the summary while the cashier types, so any change here must be mirrored
in `src/lib/api/pricing.ts` of the frontend.

    discount_cents      = round_half_up(amount_cents * discount_percent / 100)
    base_cents          = amount_cents - discount_cents
    cashback_used_cents = min(cashback_balance_cents, base_cents) if use_cashback else 0
    total_cents         = base_cents - cashback_used_cents
    points_earned       = floor(base_cents / 1000) * points_per_ten
    cashback_earned     = round_half_up(base_cents * cashback_percent / 100)

Points and cashback are earned on `base_cents` (already discounted, before the
cashback used is subtracted). An expired or cancelled card pays the full amount
and earns nothing: no discount, no points, no cashback, no cashback use.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTS_PER_POINT_STEP = 1000  # points are earned per $10


@dataclass(frozen=True)
class Breakdown:
    discount_percent: Decimal
    discount_cents: int
    base_cents: int
    cashback_used_cents: int
    total_cents: int
    points_earned: int
    cashback_earned_cents: int


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def percent_of(amount_cents: int, percent: Decimal) -> int:
    return round_half_up(Decimal(amount_cents) * Decimal(percent) / 100)


def calculate(
    amount_cents: int,
    *,
    discount_percent: Decimal,
    points_per_ten: int,
    cashback_percent: Decimal,
    cashback_balance_cents: int = 0,
    use_cashback: bool = False,
    benefits_apply: bool = True,
) -> Breakdown:
    if not benefits_apply:
        return Breakdown(
            discount_percent=Decimal(0),
            discount_cents=0,
            base_cents=amount_cents,
            cashback_used_cents=0,
            total_cents=amount_cents,
            points_earned=0,
            cashback_earned_cents=0,
        )
    discount_cents = percent_of(amount_cents, discount_percent)
    base_cents = amount_cents - discount_cents
    cashback_used = min(max(cashback_balance_cents, 0), base_cents) if use_cashback else 0
    return Breakdown(
        discount_percent=Decimal(discount_percent),
        discount_cents=discount_cents,
        base_cents=base_cents,
        cashback_used_cents=cashback_used,
        total_cents=base_cents - cashback_used,
        points_earned=(base_cents // CENTS_PER_POINT_STEP) * points_per_ten,
        cashback_earned_cents=percent_of(base_cents, cashback_percent),
    )
