"""When each fetcher last checked its source successfully (a no-op check counts).

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.create_table(
        "fetcher_check",
        sa.Column("fetcher", sa.Text, primary_key=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fetcher_check")
