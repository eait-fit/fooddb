"""fetch_run.code: the fetcher's own code version. A parser change bumps a fetcher's CODE, and
`already_done` then finds no done run at that code, so the next check re-ingests a source whose
file did not change (#63). Runs stored before the column have it null, which equals no declared
code — each versioned fetcher re-ingests once after this deploy.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    op.add_column("fetch_run", sa.Column("code", sa.Text()))


def downgrade() -> None:
    op.drop_column("fetch_run", "code")
