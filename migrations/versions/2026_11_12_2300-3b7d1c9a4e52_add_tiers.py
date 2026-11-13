"""add tiers

Revision ID: 3b7d1c9a4e52
Revises: fef05f6754ea
Create Date: 2026-11-12 23:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "3b7d1c9a4e52"
down_revision: str | Sequence[str] | None = "fef05f6754ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column(
            "finish",
            sa.Enum("bronze", "silver", "gold", "onyx", name="tierfinish"),
            nullable=False,
        ),
        sa.Column("min_points", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("points_per_ten", sa.Integer(), nullable=False),
        sa.Column("cashback_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.CheckConstraint("min_points >= 0", name="ck_tiers_min_points"),
        sa.CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100", name="ck_tiers_discount_percent"
        ),
        sa.CheckConstraint("points_per_ten >= 0", name="ck_tiers_points_per_ten"),
        sa.CheckConstraint(
            "cashback_percent >= 0 AND cashback_percent <= 100", name="ck_tiers_cashback_percent"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tiers_business_id"), "tiers", ["business_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tiers_business_id"), table_name="tiers")
    op.drop_table("tiers")
    # PostgreSQL keeps ENUM types after DROP TABLE; remove it so upgrade can run again.
    sa.Enum(name="tierfinish").drop(op.get_bind(), checkfirst=True)
