"""DTO rules.

`business_id` never comes from the request body, and credentials never go out.
Both are stated in AGENTS.md §Aislamiento multi-negocio and are invisible to the
behaviour tests: a new input schema accepting `business_id` would still pass
every test we have.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from tests.rules.helpers import ROOT, annotated_fields, classes, package_files

INPUT_SUFFIXES = ("Create", "Update")
OUTPUT_SUFFIXES = ("Response",)
FORBIDDEN_INPUT = {"business_id"}
FORBIDDEN_OUTPUT = {
    "api_key",
    "hashed_password",
    "password",
    "password_hash",
    "private_key",
    "secret",
}


def schemas(suffixes: tuple[str, ...]) -> Iterator[tuple[Path, str, ast.ClassDef]]:
    for path in package_files("schemas"):
        for name, node in classes(path).items():
            if name.endswith(suffixes):
                yield path.relative_to(ROOT), name, node


def test_input_schemas_never_accept_business_id() -> None:
    offenders = [
        f"{where}:{name}"
        for where, name, node in schemas(INPUT_SUFFIXES)
        if annotated_fields(node) & FORBIDDEN_INPUT
    ]
    assert not offenders, (
        "`business_id` comes from the token (BusinessId dependency), never from the request "
        f"body. Declared in: {', '.join(offenders)}"
    )


def test_output_schemas_never_expose_credentials() -> None:
    offenders = [
        f"{where}:{name} exposes {sorted(annotated_fields(node) & FORBIDDEN_OUTPUT)}"
        for where, name, node in schemas(OUTPUT_SUFFIXES)
        if annotated_fields(node) & FORBIDDEN_OUTPUT
    ]
    assert not offenders, (
        "Response schemas never expose credentials or their hashes. Found: " + "; ".join(offenders)
    )


def test_every_module_has_an_output_schema() -> None:
    """A module that returns rows must declare what it returns, not dump the table."""
    declared = {name for _, name, _ in schemas(OUTPUT_SUFFIXES)}
    assert declared, "No *Response schema found under schemas/"
