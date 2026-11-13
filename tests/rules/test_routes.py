"""Route shape: `/<resource>/<action>`, with the action from a closed list.

AGENTS.md, section Convenciones de código, and docs/ARCHITECTURE.md, section rutas.

Paths come from the OpenAPI schema, not from `app.routes`: the installed FastAPI
wraps included routers, so `app.routes` does not list their paths at all.
"""

from __future__ import annotations

from main import create_app

API_PREFIX = "/api/v1"

# Documented actions plus the three auth verbs already in use. Adding an action
# is a one-line change here, on purpose: the list is the convention.
# `summary`, `lookup`, `cancel` (section 3), `preview` (section 5) and `export`
# (section 6) and `send` (section 13) come from the frontend API contract.
ALLOWED_ACTIONS = {
    "cancel",
    "create",
    "delete",
    "export",
    "list",
    "login",
    "logout",
    "lookup",
    "me",
    "preview",
    "send",
    "summary",
    "update",
}

# A resource seen from another one. `/platform/business/list` (contract, section 7):
# the platform owner lists the businesses, so `business` sits between the resource
# and the action.
# `card-link` and `google-wallet` (section 13): the link to a customer's digital
# card and its Google Wallet pass; their names come from the contract.
SUB_RESOURCES = {"business", "card-link", "google-wallet"}

# The only endpoint allowed outside the versioned prefix.
UNVERSIONED = {"/health"}


def openapi_paths() -> list[str]:
    return sorted(create_app().openapi()["paths"])


def api_paths() -> list[str]:
    return [path for path in openapi_paths() if path.startswith(API_PREFIX)]


def test_every_route_matches_the_resource_action_shape() -> None:
    problems: list[str] = []
    for path in api_paths():
        segments = [segment for segment in path.removeprefix(API_PREFIX).split("/") if segment]
        if not segments:
            problems.append(f"{path}: no resource segment")
            continue

        resource, *rest = segments
        if not resource.islower() or not resource.isalnum():
            problems.append(f"{path}: resource '{resource}' must be one lowercase word")

        for segment in rest:
            if segment.startswith("{") and segment.endswith("}"):
                parameter = segment[1:-1]
                if parameter != parameter.lower() or "-" in parameter:
                    problems.append(f"{path}: path parameter '{parameter}' must be snake_case")
                continue
            if segment not in ALLOWED_ACTIONS | SUB_RESOURCES:
                problems.append(
                    f"{path}: '{segment}' is not one of the allowed actions "
                    f"{sorted(ALLOWED_ACTIONS)}"
                )

    assert not problems, (
        "Routes follow `/<resource>/<action>` (docs/ARCHITECTURE.md, section rutas):\n"
        + "\n".join(problems)
    )


def test_only_health_lives_outside_the_version_prefix() -> None:
    outside = [path for path in openapi_paths() if not path.startswith(API_PREFIX)]
    unexpected = [path for path in outside if path not in UNVERSIONED]
    assert not unexpected, f"Routes outside {API_PREFIX}: {unexpected}"
