"""API keys, stored as SHA-256 hashes only, and the per-minute request counters of the rate limit.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("scopes", ARRAY(sa.Text), nullable=False),
        sa.Column("rate_limit", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("scopes <@ array['read', 'review', 'admin'] and cardinality(scopes) > 0", name="api_key_scopes"),
        sa.CheckConstraint("rate_limit > 0", name="api_key_rate_limit"),
    )
    op.create_index("api_key_active_name", "api_key", ["name"], unique=True, postgresql_where=sa.text("revoked_at is null"))
    # Unlogged: a crash loses at most one minute of counts.
    op.create_table(
        "rate_limit",
        sa.Column("bucket", sa.Text, primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer, nullable=False),
        prefixes=["UNLOGGED"],
    )


def downgrade() -> None:
    op.drop_table("rate_limit")
    op.drop_table("api_key")
