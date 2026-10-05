"""Merge log and cannot-link pairs: every merge and split is recorded, and a split is never re-merged.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.create_table(
        "merge_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("kind", sa.Text, nullable=False),  # "merge" | "split"
        sa.Column("from_product", sa.BigInteger, sa.ForeignKey("product.id"), nullable=False),
        sa.Column("into_product", sa.BigInteger, sa.ForeignKey("product.id"), nullable=False),
        sa.Column("food_ids", ARRAY(sa.Text), nullable=False),
        sa.Column("probability", sa.Float),
        sa.Column("threshold", sa.Float),
        sa.Column("by", sa.Text),
        sa.Column("note", sa.Text),
        sa.CheckConstraint("kind in ('merge', 'split')", name="merge_log_kind"),
    )
    op.create_index("merge_log_food_ids_idx", "merge_log", ["food_ids"], postgresql_using="gin")
    op.create_table(
        "cannot_link",
        sa.Column("food_a", sa.Text, sa.ForeignKey("food.id"), nullable=False),
        sa.Column("food_b", sa.Text, sa.ForeignKey("food.id"), nullable=False),
        sa.Column("by", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("food_a", "food_b"),
        sa.CheckConstraint("food_a < food_b", name="cannot_link_ordered"),
    )


def downgrade() -> None:
    op.drop_table("cannot_link")
    op.drop_table("merge_log")
