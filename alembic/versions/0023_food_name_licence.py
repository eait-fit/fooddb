"""food_name.licence: the licence the name rides under — the record's own for source-stated
names, AGPL-3.0 for agent-written ones (origin='mt').

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    op.add_column("food_name", sa.Column("licence", sa.Text, nullable=False, server_default=""))
    op.execute("update food_name set licence = food.licence from food where food_name.food_id = food.id")


def downgrade() -> None:
    op.drop_column("food_name", "licence")
