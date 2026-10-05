"""Nightly snapshots of resolved values.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "snapshot",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("products", sa.Integer, nullable=False),
    )
    op.create_table(
        "snapshot_value",
        sa.Column("day", sa.Date, sa.ForeignKey("snapshot.day", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.Text, nullable=False),  # "core" | "all" (include=off)
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("nutrient", sa.Text, nullable=False),
        sa.Column("value_per_100", sa.Numeric, nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.Column("basis", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("licence", sa.Text, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("day", "scope", "product_id", "nutrient"),
    )


def downgrade() -> None:
    op.drop_table("snapshot_value")
    op.drop_table("snapshot")
