"""Review decisions: who moved a pending observation to accepted or rejected, when, and why.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.add_column("observation", sa.Column("reviewed_by", sa.Text))
    op.add_column("observation", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("observation", sa.Column("review_note", sa.Text))
    op.create_index("observation_pending_idx", "observation", ["food_id"], postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("observation_pending_idx", "observation")
    op.drop_column("observation", "review_note")
    op.drop_column("observation", "reviewed_at")
    op.drop_column("observation", "reviewed_by")
