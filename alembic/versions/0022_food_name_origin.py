"""food_name.origin: a name the source stated vs an agent-written one (origin='mt', the
data/names/mt/*.tsv sets). A table load restates only the source's own rows, so shipped
translations survive a refetch; the primary key widens so a source's 'de' name and ours can
stand side by side.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    op.add_column("food_name", sa.Column("origin", sa.Text, nullable=False, server_default="source"))
    op.drop_constraint("food_name_pkey", "food_name", type_="primary")
    op.create_primary_key("food_name_pkey", "food_name", ["food_id", "lang", "origin"])


def downgrade() -> None:
    op.execute("delete from food_name where origin <> 'source'")
    op.drop_constraint("food_name_pkey", "food_name", type_="primary")
    op.create_primary_key("food_name_pkey", "food_name", ["food_id", "lang"])
    op.drop_column("food_name", "origin")
