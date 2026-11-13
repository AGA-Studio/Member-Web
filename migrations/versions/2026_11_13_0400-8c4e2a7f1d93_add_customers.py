"""add customers

Revision ID: 8c4e2a7f1d93
Revises: 3b7d1c9a4e52
Create Date: 2026-11-13 04:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "8c4e2a7f1d93"
down_revision: str | Sequence[str] | None = "3b7d1c9a4e52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=True),
        sa.Column("issued_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("valid_until", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("cancelled_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["tier_id"], ["tiers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "code", name="uq_customers_business_code"),
        sa.UniqueConstraint("business_id", "email", name="uq_customers_business_email"),
    )
    op.create_index(op.f("ix_customers_business_id"), "customers", ["business_id"], unique=False)
    op.create_index(op.f("ix_customers_tier_id"), "customers", ["tier_id"], unique=False)
    op.create_index(op.f("ix_customers_valid_until"), "customers", ["valid_until"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_customers_valid_until"), table_name="customers")
    op.drop_index(op.f("ix_customers_tier_id"), table_name="customers")
    op.drop_index(op.f("ix_customers_business_id"), table_name="customers")
    op.drop_table("customers")
