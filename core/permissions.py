"""What each role can do: the single permission matrix (issue #72).

Routes ask for a permission (`require_permission(Permission.CUSTOMERS_MANAGE)`),
never for a role, so adding a role only touches this table. Roles are fixed in
code on purpose: a small business has nobody to administer per-user ACLs.

The plan of the business (what it *includes*) is a separate question from the
role (who *may* use it) and does not live here.
"""

from enum import StrEnum

from models.user_model import Role


class Permission(StrEnum):
    CHECKOUT = "checkout"  # Charge at the counter and read the receipts they charged.
    RECEIPTS_ALL = "receipts.all"  # Read any receipt of the business, not only their own.
    CUSTOMERS_LOOKUP = "customers.lookup"  # Find a card by its code at the counter.
    CUSTOMERS_MANAGE = "customers.manage"  # List, create, edit, renew and cancel customers.
    MOVEMENTS_READ = "movements.read"  # Purchase/point history, its totals and the CSV export.
    TIERS_READ = "tiers.read"
    TIERS_MANAGE = "tiers.manage"
    USERS_MANAGE = "users.manage"
    BUSINESS_MANAGE = "business.manage"  # Name, validity, color and logo of the business.
    AI_CHAT = "ai.chat"  # Read-only chat about the business's own data (issue #73).
    PLATFORM = "platform"  # Status and usage of every business, never their data.


_COUNTER = {Permission.CHECKOUT, Permission.CUSTOMERS_LOOKUP, Permission.TIERS_READ}
_MANAGER = _COUNTER | {
    Permission.RECEIPTS_ALL,
    Permission.CUSTOMERS_MANAGE,
    Permission.MOVEMENTS_READ,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PLATFORM: frozenset({Permission.PLATFORM}),
    Role.ADMIN: frozenset(
        _MANAGER
        | {
            Permission.TIERS_MANAGE,
            Permission.USERS_MANAGE,
            Permission.BUSINESS_MANAGE,
            Permission.AI_CHAT,
        }
    ),
    # Shift lead: the counter plus customers and history; no tiers, users or settings.
    Role.MANAGER: frozenset(_MANAGER),
    Role.EMPLOYEE: frozenset(_COUNTER),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_of(role: Role) -> list[str]:
    """Sorted, for `/auth/me`: the frontend shows or hides by permission, not by role."""
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))
