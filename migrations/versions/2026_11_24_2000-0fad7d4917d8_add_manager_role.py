"""add manager role

Revision ID: 0fad7d4917d8
Revises: e4a7b9c1d3f5
Create Date: 2026-11-24 20:00:00.000000+00:00

The `manager` role (issue #72): counter, customers and history, without tiers,
users or settings. What it can do lives in `core/permissions.py`, not here.

Only PostgreSQL stores `role` as a native enum; SQLite keeps a plain string, so
there is nothing to change there.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0fad7d4917d8"
down_revision: str | Sequence[str] | None = "e4a7b9c1d3f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TYPE role ADD VALUE IF NOT EXISTS 'manager' AFTER 'admin'")


def downgrade() -> None:
    """PostgreSQL cannot drop an enum value: the type is rebuilt without it.

    Managers become employees (the closest role with fewer permissions), so no
    one gains access by going back.
    """
    if op.get_bind().dialect.name != "postgresql":
        op.execute("UPDATE users SET role = 'employee' WHERE role = 'manager'")
        return
    op.execute("UPDATE users SET role = 'employee' WHERE role = 'manager'")
    op.execute("ALTER TYPE role RENAME TO role_old")
    op.execute("CREATE TYPE role AS ENUM ('platform', 'admin', 'employee')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE role USING role::text::role")
    op.execute("DROP TYPE role_old")
