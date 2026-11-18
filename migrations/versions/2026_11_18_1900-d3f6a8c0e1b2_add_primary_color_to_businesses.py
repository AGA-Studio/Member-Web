"""add primary_color to businesses

Revision ID: d3f6a8c0e1b2
Revises: 146733b94fa0
Create Date: 2026-11-18 19:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d3f6a8c0e1b2"
down_revision: str | Sequence[str] | None = "146733b94fa0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: existing businesses keep Member+ blue until the admin picks a color.
    op.add_column(
        "businesses",
        sa.Column("primary_color", sqlmodel.sql.sqltypes.AutoString(length=7), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("businesses", "primary_color")
