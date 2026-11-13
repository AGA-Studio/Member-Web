"""add card deliveries

Revision ID: a7c3e9f2b815
Revises: 5d2f8b6c1a47
Create Date: 2026-11-13 06:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a7c3e9f2b815"
down_revision: str | Sequence[str] | None = "5d2f8b6c1a47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("revoked_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("last_sent_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_card_deliveries_token_hash"),
    )
    op.create_index(
        op.f("ix_card_deliveries_business_id"), "card_deliveries", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_card_deliveries_customer_id"), "card_deliveries", ["customer_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_card_deliveries_customer_id"), table_name="card_deliveries")
    op.drop_index(op.f("ix_card_deliveries_business_id"), table_name="card_deliveries")
    op.drop_table("card_deliveries")
