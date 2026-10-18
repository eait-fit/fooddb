"""One snapshot only, the current one: drop every day but the newest.

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    # snapshot_value.day cascades on snapshot.day: deleting the old days deletes their values.
    op.execute("delete from snapshot where day <> (select max(day) from snapshot)")


def downgrade() -> None:
    pass  # the deleted days cannot be restored; the next build keeps only its own day anyway
