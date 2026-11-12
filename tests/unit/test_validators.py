"""Unit tests for schemas/validators.py (H5: person names)."""

import pytest
from pydantic import BaseModel, ValidationError

from schemas.validators import PersonName


class Model(BaseModel):
    name: PersonName


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ana", "Ana"),
        ("Iván", "Iván"),
        ("José Luis", "José Luis"),
        ("María-José", "María-José"),
        ("O'Connor", "O'Connor"),
        ("D’Angelo", "D’Angelo"),
        ("Ñandú", "Ñandú"),
        ("Bo", "Bo"),
        ("  José   Luis  ", "José Luis"),
        ("Ana\tMaría", "Ana María"),
    ],
)
def test_valid_names_are_normalized(raw: str, expected: str) -> None:
    assert Model(name=raw).name == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "A", " A ", "--", "''", "Ana2", "123", "@@@", "Ana.", "Ana_Luis", "José 😀"],
    ids=[
        "empty",
        "spaces",
        "one-letter",
        "one-letter-spaced",
        "only-hyphens",
        "only-apostrophes",
        "digit",
        "numbers",
        "symbols",
        "period",
        "underscore",
        "emoji",
    ],
)
def test_invalid_names_are_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        Model(name=raw)


def test_max_length() -> None:
    Model(name="a" * 120)
    with pytest.raises(ValidationError):
        Model(name="a" * 121)


def test_error_messages() -> None:
    with pytest.raises(ValidationError, match="at least 2 letters"):
        Model(name="A")
    with pytest.raises(ValidationError, match="only contain letters"):
        Model(name="Ana2")
