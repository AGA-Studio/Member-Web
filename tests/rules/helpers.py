"""Helpers for the convention tests.

These tests read the source tree instead of calling the API: they exist to stop
the *next* module from breaking a rule, not to check the current behaviour.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def package_files(*packages: str) -> list[Path]:
    """Every .py file inside the given top-level packages, __pycache__ excluded."""
    files: list[Path] = []
    for package in packages:
        base = ROOT / package
        if not base.is_dir():
            continue
        files.extend(path for path in sorted(base.rglob("*.py")) if "__pycache__" not in path.parts)
    return files


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def classes(path: Path) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in ast.walk(tree(path)) if isinstance(node, ast.ClassDef)}


def annotated_fields(node: ast.ClassDef) -> set[str]:
    """Field names declared with a type annotation directly in the class body."""
    return {
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }


def router_prefixes() -> dict[str, str]:
    """Module name -> router prefix, for every api/v1/*_api.py."""
    prefixes: dict[str, str] = {}
    for path in sorted((ROOT / "api" / "v1").glob("*_api.py")):
        for node in ast.walk(tree(path)):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "APIRouter":
                continue
            for keyword in node.keywords:
                if keyword.arg != "prefix":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    prefixes[path.stem] = keyword.value.value
    return prefixes


def table_name(node: ast.ClassDef) -> str | None:
    """The `__tablename__` of an SQLModel class, or None when it is not a table."""
    for statement in node.body:
        if not isinstance(statement, ast.Assign):
            continue
        targets = statement.targets
        if not isinstance(targets[0], ast.Name) or targets[0].id != "__tablename__":
            continue
        if not isinstance(statement.value, ast.Constant) or not isinstance(
            statement.value.value, str
        ):
            return None
        return statement.value.value
    return None
