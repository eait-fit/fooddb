"""Index merged_into: a snapshot read finds the products merged into one after the build.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_index("product_merged_into_idx", "product", ["merged_into"])


def downgrade() -> None:
    op.drop_index("product_merged_into_idx", "product")
