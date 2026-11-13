"""Pure helpers of services/customer_service.py (no database)."""

from datetime import UTC, datetime

import pytest

from services.customer_service import (
    CODE_ALPHABET,
    CODE_LENGTH,
    CODE_PREFIX,
    add_months,
    generate_code,
    normalize_code,
)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (datetime(2026, 3, 17, 18, tzinfo=UTC), 12, datetime(2027, 3, 17, 18, tzinfo=UTC)),
        (datetime(2026, 1, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2028, 2, 29, tzinfo=UTC), 12, datetime(2029, 2, 28, tzinfo=UTC)),
        (datetime(2026, 11, 13, tzinfo=UTC), 2, datetime(2027, 1, 13, tzinfo=UTC)),
    ],
)
def test_add_months(start, months, expected) -> None:
    assert add_months(start, months) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("mp-4f7k2", "MP-4F7K2"), (" MP-4F7K2\n", "MP-4F7K2"), ("MP- 4F 7K2", "MP-4F7K2")],
)
def test_normalize_code(raw, expected) -> None:
    assert normalize_code(raw) == expected


def test_generated_codes_use_the_safe_alphabet() -> None:
    for _ in range(200):
        code = generate_code()
        assert code.startswith(CODE_PREFIX)
        assert len(code) == len(CODE_PREFIX) + CODE_LENGTH
        assert set(code[len(CODE_PREFIX) :]) <= set(CODE_ALPHABET)


def test_alphabet_has_no_look_alikes() -> None:
    assert not set(CODE_ALPHABET) & set("01OIL")


def test_codes_are_random() -> None:
    assert len({generate_code() for _ in range(200)}) > 190
