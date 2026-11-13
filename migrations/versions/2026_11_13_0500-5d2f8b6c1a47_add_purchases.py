"""add purchases

Revision ID: 5d2f8b6c1a47
Revises: 8c4e2a7f1d93
Create Date: 2026-11-13 05:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5d2f8b6c1a47"
down_revision: str | Sequence[str] | None = "8c4e2a7f1d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIER_FINISHES = ("bronze", "silver", "gold", "onyx")

# `tierfinish` already exists in PostgreSQL (created with `tiers`): reuse it.
tier_finish = sa.Enum(*TIER_FINISHES, name="tierfinish").with_variant(
    postgresql.ENUM(*TIER_FINISHES, name="tierfinish", create_type=False), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("cashier_id", sa.Integer(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=False),
        sa.Column("tier_name", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=False),
        sa.Column("tier_finish", tier_finish, nullable=False),
        sa.Column(
            "card_status",
            sa.Enum("active", "expired", "cancelled", name="cardstatus"),
            nullable=False,
        ),
        sa.Column("concept", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("discount_cents", sa.Integer(), nullable=False),
        sa.Column("cashback_used_cents", sa.Integer(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("points_earned", sa.Integer(), nullable=False),
        sa.Column("cashback_earned_cents", sa.Integer(), nullable=False),
        sa.Column("points_balance_after", sa.Integer(), nullable=False),
        sa.Column("cashback_balance_after_cents", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_purchases_amount_cents"),
        sa.CheckConstraint("cashback_used_cents >= 0", name="ck_purchases_cashback_used_cents"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["cashier_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["tier_id"], ["tiers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "idempotency_key", name="uq_purchases_business_idempotency_key"
        ),
    )
    op.create_index(op.f("ix_purchases_business_id"), "purchases", ["business_id"], unique=False)
    op.create_index(op.f("ix_purchases_cashier_id"), "purchases", ["cashier_id"], unique=False)
    op.create_index(op.f("ix_purchases_created_at"), "purchases", ["created_at"], unique=False)
    op.create_index(op.f("ix_purchases_customer_id"), "purchases", ["customer_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_purchases_customer_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_created_at"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_cashier_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_business_id"), table_name="purchases")
    op.drop_table("purchases")
    # `tierfinish` belongs to `tiers` and stays; `cardstatus` is only ours.
    sa.Enum(name="cardstatus").drop(op.get_bind(), checkfirst=True)
