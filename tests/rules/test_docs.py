"""The repository docs stay current.

AGENTS.md, section Documentación: every change to models or endpoints is reflected in
`docs/ARCHITECTURE.md` in the same commit or the next one. Until now that was a
promise; these tests make it checkable.
"""

from __future__ import annotations

import ast
import re

from main import create_app
from tests.rules.helpers import ROOT, package_files, table_name, tree

ARCHITECTURE = ROOT / "docs" / "ARCHITECTURE.md"
API_PREFIX = "/api/v1"

ER_BLOCK = re.compile(r"erDiagram\n(?P<body>.*?)```", re.DOTALL)
ENTITY_LINE = re.compile(r"^ {4}(?P<name>[a-z_]+) \{", re.MULTILINE)


def documented_tables() -> set[str]:
    match = ER_BLOCK.search(ARCHITECTURE.read_text(encoding="utf-8"))
    assert match, "docs/ARCHITECTURE.md has no ```mermaid erDiagram block"
    return set(ENTITY_LINE.findall(match.group("body")))


def model_tables() -> set[str]:
    tables = set()
    for path in package_files("models"):
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.ClassDef) and (name := table_name(node)):
                tables.add(name)
    return tables


def documented_paths() -> set[str]:
    return set(re.findall(r"`(?P<path>/[a-z0-9/{}_]+)`", ARCHITECTURE.read_text(encoding="utf-8")))


def api_paths() -> list[str]:
    return sorted(create_app().openapi()["paths"])


def test_every_model_table_is_in_the_er_diagram() -> None:
    missing = model_tables() - documented_tables()
    assert not missing, (
        f"docs/ARCHITECTURE.md, section erDiagram is missing {sorted(missing)}. "
        "A models/ change ships with its doc update."
    )


def test_every_documented_table_exists_in_the_models() -> None:
    stale = documented_tables() - model_tables()
    assert not stale, (
        f"docs/ARCHITECTURE.md documents tables that no model defines: {sorted(stale)}"
    )


def test_every_route_is_documented() -> None:
    documented = documented_paths()
    missing = [path for path in api_paths() if path not in documented]
    assert not missing, (
        "docs/ARCHITECTURE.md, section endpoints does not list these routes "
        f"(write them as `{API_PREFIX}/...` in the table): {missing}"
    )
