"""add plans

Revision ID: 613f061889d5
Revises: 0fad7d4917d8
Create Date: 2026-11-24 21:00:00.000000+00:00

The plan catalog (issue #70) and the plan of each business. The rows are a
frozen copy of `services/plan_service.CATALOG` as it was when this migration
was written: a later change of numbers is a new migration, never an edit here
(`tests/rules` does not compare them on purpose).

Businesses that already exist go to the `business` plan without a trial, so
nothing they use today (logo, photos, export) gets closed by the limits that a
later change enforces. New businesses start on the default plan.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "613f061889d5"
down_revision: str | Sequence[str] | None = "0fad7d4917d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ROLE = "memberplus_tenant"

PLANS = [
    # key, name, price, customers, users, devices, history, images, exports, ai, ai_msgs,
    # trial, default, public, order
    ("free", "Gratis", 0, 50, 2, 0, 60, False, False, False, 0, 0, True, True, 0),
    ("counter", "Mostrador", 19_900, 300, 3, 1, 365, True, True, False, 0, 0, False, True, 1),
    ("business", "Negocio", 39_900, 1_000, 8, 2, None, True, True, True, 100, 30, False, True, 2),
    ("chain", "Cadena", 79_900, 3_000, 20, 5, None, True, True, True, 300, 0, False, False, 3),
]
COLUMNS = (
    "key",
    "name",
    "price_cents",
    "max_customers",
    "max_users",
    "max_devices",
    "history_days",
    "images_enabled",
    "exports_enabled",
    "ai_enabled",
    "ai_messages_month",
    "trial_days",
    "is_default",
    "is_public",
    "sort_order",
)


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("max_customers", sa.Integer(), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_devices", sa.Integer(), nullable=True),
        sa.Column("history_days", sa.Integer(), nullable=True),
        sa.Column("images_enabled", sa.Boolean(), nullable=False),
        sa.Column("exports_enabled", sa.Boolean(), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False),
        sa.Column("ai_messages_month", sa.Integer(), nullable=False),
        sa.Column("trial_days", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.bulk_insert(plans, [dict(zip(COLUMNS, row, strict=True)) for row in PLANS])

    with op.batch_alter_table("businesses") as batch:
        batch.add_column(sa.Column("plan_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("trial_ends_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("unit_price_cents", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_businesses_plan_id_plans", "plans", ["plan_id"], ["id"])

    op.execute(
        "UPDATE businesses SET plan_id = (SELECT id FROM plans WHERE key = 'business'),"
        " unit_price_cents = (SELECT price_cents FROM plans WHERE key = 'business')"
    )

    if op.get_bind().dialect.name == "postgresql":
        # The catalog is global and read-only for a business: Row Level Security
        # does not apply (no business_id), so the tenant role only reads it.
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{TENANT_ROLE}') THEN "
            f"REVOKE INSERT, UPDATE, DELETE ON plans FROM {TENANT_ROLE}; "
            f"GRANT SELECT ON plans TO {TENANT_ROLE}; END IF; END $$"
        )


def downgrade() -> None:
    with op.batch_alter_table("businesses") as batch:
        batch.drop_constraint("fk_businesses_plan_id_plans", type_="foreignkey")
        batch.drop_column("unit_price_cents")
        batch.drop_column("trial_ends_at")
        batch.drop_column("plan_id")
    op.drop_table("plans")
