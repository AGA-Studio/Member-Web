"""Reusable field types for input schemas."""

from typing import Annotated

from pydantic import AfterValidator, Field

PERSON_NAME_MIN_LETTERS = 2
PERSON_NAME_MAX_LENGTH = 120
_ALLOWED_SEPARATORS = frozenset(" -'’")


def normalize_person_name(value: str) -> str:
    """Clean and validate a person's name.

    - Trims and collapses whitespace: "  José   Luis " -> "José Luis".
    - Only letters (any alphabet, accents and ñ included), spaces, hyphens and
      apostrophes: accepts "María-José" and "O'Connor", rejects "Ana2" or "@@@".
    - At least 2 letters: rejects "   ", "A" and "--".
    """
    name = " ".join(value.split())
    if any(not (char.isalpha() or char in _ALLOWED_SEPARATORS) for char in name):
        raise ValueError("Name can only contain letters, spaces, hyphens and apostrophes")
    if sum(char.isalpha() for char in name) < PERSON_NAME_MIN_LETTERS:
        raise ValueError(f"Name must contain at least {PERSON_NAME_MIN_LETTERS} letters")
    return name


PersonName = Annotated[
    str,
    Field(min_length=1, max_length=PERSON_NAME_MAX_LENGTH, examples=["José Luis"]),
    AfterValidator(normalize_person_name),
]
