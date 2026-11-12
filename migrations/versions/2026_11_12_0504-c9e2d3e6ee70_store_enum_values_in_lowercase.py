"""store enum values in lowercase

The first migration stored enum member NAMES ('ADMIN', 'TRIAL') because that is
SQLAlchemy's default. The models now store the VALUES ('admin', 'trial'), the same
strings the API returns, so hand-written SQL (seeds, psql) uses lowercase too.

- PostgreSQL: rename the labels of the native ENUM types (existing rows follow).
- SQLite: enums are plain text, so the rows are updated.

Revision ID: c9e2d3e6ee70
Revises: f689e0ec2cd6
Create Date: 2026-11-12 05:04:34.287806+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9e2d3e6ee70"
down_revision: str | Sequence[str] | None = "f689e0ec2cd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, postgres enum type, member names)
ENUMS = [
    ("users", "role", "role", ["PLATFORM", "ADMIN", "EMPLOYEE"]),
    ("businesses", "status", "businessstatus", ["TRIAL", "ACTIVE", "SUSPENDED"]),
]


def _convert(to_lower: bool) -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    for table, column, enum_type, names in ENUMS:
        if is_postgres:
            for name in names:
                old, new = (name, name.lower()) if to_lower else (name.lower(), name)
                op.execute(f"ALTER TYPE {enum_type} RENAME VALUE '{old}' TO '{new}'")
        else:
            function = "lower" if to_lower else "upper"
            op.execute(f"UPDATE {table} SET {column} = {function}({column})")


def upgrade() -> None:
    _convert(to_lower=True)


def downgrade() -> None:
    _convert(to_lower=False)
