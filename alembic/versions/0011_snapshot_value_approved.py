"""Snapshot values remember whether a human approved the label read they come from.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.add_column("snapshot_value", sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("snapshot_value", "approved")
