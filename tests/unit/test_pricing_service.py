"""services/pricing_service.py: the checkout formula (API contract, section 5.1)."""

from decimal import Decimal

import pytest

from services.pricing_service import calculate, percent_of, round_half_up

GOLD = {"discount_percent": Decimal("15"), "points_per_ten": 1, "cashback_percent": Decimal("3")}


def test_rubric_example_1000_pesos_in_gold() -> None:
    b = calculate(100_000, **GOLD)
    assert (b.discount_cents, b.base_cents, b.total_cents) == (15_000, 85_000, 85_000)
    assert (b.points_earned, b.cashback_earned_cents, b.cashback_used_cents) == (85, 2_550, 0)


def test_points_and_cashback_are_earned_before_subtracting_the_cashback_used() -> None:
    b = calculate(10_000, **GOLD, cashback_balance_cents=2_550, use_cashback=True)
    assert (b.base_cents, b.cashback_used_cents, b.total_cents) == (8_500, 2_550, 5_950)
    assert (b.points_earned, b.cashback_earned_cents) == (8, 255)


def test_cashback_used_never_exceeds_the_base() -> None:
    b = calculate(1_000, **GOLD, cashback_balance_cents=25_500, use_cashback=True)
    assert (b.base_cents, b.cashback_used_cents, b.total_cents) == (850, 850, 0)


def test_balance_is_ignored_without_use_cashback() -> None:
    assert calculate(1_000, **GOLD, cashback_balance_cents=500).cashback_used_cents == 0


def test_negative_balance_spends_nothing() -> None:
    assert calculate(1_000, **GOLD, cashback_balance_cents=-5, use_cashback=True).total_cents == 850


def test_points_round_down_per_ten_pesos() -> None:
    assert (
        calculate(
            99_999, discount_percent=Decimal(0), points_per_ten=2, cashback_percent=Decimal(0)
        ).points_earned
        == 198
    )


@pytest.mark.parametrize(
    ("amount", "percent", "expected"),
    [(1_000, "15", 150), (850, "3", 26), (50, "1", 1), (49, "1", 0), (333, "33.33", 111)],
)
def test_percent_rounds_half_up_to_the_cent(amount, percent, expected) -> None:
    assert percent_of(amount, Decimal(percent)) == expected


def test_round_half_up() -> None:
    assert [round_half_up(Decimal(v)) for v in ("0.5", "1.5", "2.5", "2.49")] == [1, 2, 3, 2]


def test_disabled_benefits_charge_the_full_amount() -> None:
    b = calculate(
        100_000, **GOLD, cashback_balance_cents=9_999, use_cashback=True, benefits_apply=False
    )
    assert (b.discount_percent, b.discount_cents, b.total_cents) == (0, 0, 100_000)
    assert (b.points_earned, b.cashback_earned_cents, b.cashback_used_cents) == (0, 0, 0)


def test_tier_with_every_benefit_at_zero() -> None:
    zero = {"discount_percent": Decimal(0), "points_per_ten": 0, "cashback_percent": Decimal(0)}
    b = calculate(12_345, **zero)
    assert (b.total_cents, b.points_earned, b.cashback_earned_cents) == (12_345, 0, 0)
