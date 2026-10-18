"""food.markets: the markets a record is sold in (OFF's countries_tags), for ?country= ranking.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.add_column("food", sa.Column("markets", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("food", "markets")
