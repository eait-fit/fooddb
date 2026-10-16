"""A trigram index on the core layer's names alone: a search without OFF stops reading ~3M OFF names.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    op.create_index("food_core_name_trgm_idx", "food", ["name"], postgresql_using="gin",
                    postgresql_ops={"name": "gin_trgm_ops"}, postgresql_where=sa.text("layer = 'core'"))


def downgrade() -> None:
    op.drop_index("food_core_name_trgm_idx", "food")
