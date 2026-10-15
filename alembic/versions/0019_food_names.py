"""food_name: a record's names in other languages, so a search in the table's own language finds it.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    op.create_table(
        "food_name",
        sa.Column("food_id", sa.Text, sa.ForeignKey("food.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("lang", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_index("food_name_name_trgm_idx", "food_name", ["name"], postgresql_using="gin",
                    postgresql_ops={"name": "gin_trgm_ops"})


def downgrade() -> None:
    op.drop_table("food_name")
