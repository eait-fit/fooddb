"""The request log (one row per API request, route template only) and the admin action log.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.create_table(
        "request_log",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("route", sa.Text, nullable=False),
        sa.Column("status", sa.SmallInteger, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("key_id", sa.BigInteger),
        sa.Column("key_name", sa.Text),
        sa.Column("account_id", sa.BigInteger),
        sa.Column("ip_hash", sa.Text),
    )
    op.create_index("request_log_at_idx", "request_log", ["at"])
    op.create_table(
        "admin_action",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("by", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_action")
    op.drop_index("request_log_at_idx", "request_log")
    op.drop_table("request_log")
