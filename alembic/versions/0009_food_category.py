"""food.category: the fooddb category a source record maps to, for the range checks.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.add_column("food", sa.Column("category", sa.Text))


def downgrade() -> None:
    op.drop_column("food", "category")
