"""add card emails

Revision ID: b8d4f0a3c926
Revises: a7c3e9f2b815
Create Date: 2026-11-13 07:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b8d4f0a3c926"
down_revision: str | Sequence[str] | None = "a7c3e9f2b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_card_emails_business_id"), "card_emails", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_card_emails_customer_id"), "card_emails", ["customer_id"], unique=False
    )
    op.create_index(op.f("ix_card_emails_sent_at"), "card_emails", ["sent_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_card_emails_sent_at"), table_name="card_emails")
    op.drop_index(op.f("ix_card_emails_customer_id"), table_name="card_emails")
    op.drop_index(op.f("ix_card_emails_business_id"), table_name="card_emails")
    op.drop_table("card_emails")
