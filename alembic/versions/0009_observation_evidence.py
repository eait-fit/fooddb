"""Observation evidence (the label photo a value was read from), and the contribute scope for API keys.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def _scopes(allowed: str) -> None:
    op.drop_constraint("api_key_scopes", "api_key", type_="check")
    op.create_check_constraint("api_key_scopes", "api_key", f"scopes <@ array[{allowed}] and cardinality(scopes) > 0")


def upgrade() -> None:
    op.add_column("observation", sa.Column("evidence", sa.Text))
    _scopes("'read', 'contribute', 'review', 'admin'")


def downgrade() -> None:
    op.execute("update api_key set scopes = array_remove(scopes, 'contribute')")
    op.execute("update api_key set revoked_at = now(), scopes = '{read}' where scopes = '{}'")
    _scopes("'read', 'review', 'admin'")
    op.drop_column("observation", "evidence")
