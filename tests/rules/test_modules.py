"""Module wiring.

A router that exists but is not registered in `API_V1_ROUTERS` is dead code, and
a business-scoped module without an isolation test is the one gap the behaviour
suite cannot see: it only tests the modules that already exist.
"""

from __future__ import annotations

from main import API_V1_ROUTERS
from tests.rules.helpers import ROOT, router_prefixes

API_DIR = ROOT / "api" / "v1"
ISOLATION_DIR = ROOT / "tests" / "api"


def isolation_sources() -> str:
    """Every isolation test file, concatenated."""
    files = sorted(ISOLATION_DIR.glob("test_isolation*.py"))
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_every_router_module_is_registered_in_main() -> None:
    registered = {router.prefix for router in API_V1_ROUTERS}
    unregistered = {
        module: prefix for module, prefix in router_prefixes().items() if prefix not in registered
    }
    assert not unregistered, (
        "These router modules exist but are not in API_V1_ROUTERS (main.py), so FastAPI never "
        f"includes them: {unregistered}"
    )


def test_every_registered_router_comes_from_a_module() -> None:
    declared = set(router_prefixes().values())
    registered = {router.prefix for router in API_V1_ROUTERS}
    assert registered <= declared, (
        f"Registered in main.py without an api/v1/*_api.py module: {sorted(registered - declared)}"
    )


def test_every_business_scoped_router_has_an_isolation_test() -> None:
    sources = {path.stem: path.read_text(encoding="utf-8") for path in API_DIR.glob("*_api.py")}
    isolation = isolation_sources()
    problems = [
        f"{module} ({prefix}): no test asserting another business sees 0 rows"
        for module, prefix in router_prefixes().items()
        if "BusinessId" in sources[module] and f"/api/v1{prefix}" not in isolation
    ]
    assert not problems, (
        "Every business-scoped module needs its isolation test (AGENTS.md §Aislamiento "
        "multi-negocio, one of the MVP acceptance criteria):\n" + "\n".join(problems)
    )
