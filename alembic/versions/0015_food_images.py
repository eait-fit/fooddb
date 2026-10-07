"""Photo references of Open Food Facts records (front and nutrition panel): lang and rev, never bytes.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    op.add_column("food", sa.Column("images", JSONB))


def downgrade() -> None:
    op.drop_column("food", "images")
