"""A record seen again at the same observed_at can store a second row for a field, such as a withdrawal.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.drop_constraint("observation_once", "observation", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("observation_once", "observation", ["food_id", "nutrient", "source", "observed_at"])
