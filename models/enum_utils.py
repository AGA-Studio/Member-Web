"""Helpers for storing Python enums in the database."""

from enum import Enum


def enum_values(enum_class: type[Enum]) -> list[str]:
    """Store the enum *value* ("admin"), not the member name ("ADMIN").

    Used as `values_callable` so the database, the API and hand-written SQL
    (seeds, psql queries) all use the same lowercase strings.
    """
    return [member.value for member in enum_class]
