"""add membership payments and validity months

Revision ID: c1e5a7b9d2f4
Revises: b8d4f0a3c926
Create Date: 2026-11-13 08:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c1e5a7b9d2f4"
down_revision: str | Sequence[str] | None = "b8d4f0a3c926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("validity_months", sa.Integer(), server_default="12", nullable=False),
    )
    op.create_table(
        "membership_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=False),
        sa.Column("tier_name", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("kind", sa.Enum("new", "renewal", name="paymentkind"), nullable=False),
        sa.Column(
            "method", sa.Enum("cash", "card", "transfer", name="paymentmethod"), nullable=False
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("period_start", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("period_end", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_membership_payments_amount_cents"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["tier_id"], ["tiers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_membership_payments_business_id"),
        "membership_payments",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_membership_payments_created_at"),
        "membership_payments",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_membership_payments_customer_id"),
        "membership_payments",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_membership_payments_customer_id"), table_name="membership_payments")
    op.drop_index(op.f("ix_membership_payments_created_at"), table_name="membership_payments")
    op.drop_index(op.f("ix_membership_payments_business_id"), table_name="membership_payments")
    op.drop_table("membership_payments")
    sa.Enum(name="paymentmethod").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="paymentkind").drop(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("businesses") as batch:
        batch.drop_column("validity_months")
