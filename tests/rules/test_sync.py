"""The project is synchronous by decision (AGENTS.md §Stack y comandos).

`main.py` is outside the scanned packages on purpose: FastAPI's lifespan
protocol requires `async def lifespan`.
"""

from __future__ import annotations

import ast

from tests.rules.helpers import ROOT, package_files, tree

APPLICATION_PACKAGES = ("api", "core", "db", "models", "schemas", "scripts", "services")


def test_no_async_functions_in_the_application() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{node.lineno} async def {node.name}()"
        for path in package_files(*APPLICATION_PACKAGES)
        for node in ast.walk(tree(path))
        if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert not offenders, (
        "The project is synchronous (SQLModel sync + psycopg sync). Switching a module to "
        "async needs a team decision first, not a PR surprise:\n" + "\n".join(offenders)
    )
