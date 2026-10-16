"""Search ignores diacritics: the name trigram indexes move onto f_unaccent(name), an IMMUTABLE
wrapper — unaccent() itself is only STABLE, so it cannot be indexed. New indexes are built first
under temporary names, then the plain ones are dropped and the new ones renamed into place.

Revision ID: 0021
Revises: 0020
"""

from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    op.execute("create extension if not exists unaccent")
    op.execute(
        "create or replace function f_unaccent(text) returns text "
        "language sql immutable parallel safe strict as "
        "$$ select public.unaccent('public.unaccent', $1) $$"
    )
    op.execute("create index food_name_trgm_unaccent_idx on food using gin (f_unaccent(name) gin_trgm_ops)")
    op.execute("create index food_core_name_trgm_unaccent_idx on food using gin (f_unaccent(name) gin_trgm_ops) "
               "where layer = 'core'")
    op.execute("create index food_name_name_trgm_unaccent_idx on food_name using gin (f_unaccent(name) gin_trgm_ops)")
    op.drop_index("food_name_trgm_idx", "food")
    op.drop_index("food_core_name_trgm_idx", "food")
    op.drop_index("food_name_name_trgm_idx", "food_name")
    op.execute("alter index food_name_trgm_unaccent_idx rename to food_name_trgm_idx")
    op.execute("alter index food_core_name_trgm_unaccent_idx rename to food_core_name_trgm_idx")
    op.execute("alter index food_name_name_trgm_unaccent_idx rename to food_name_name_trgm_idx")


def downgrade() -> None:
    op.execute("create index food_name_trgm_plain_idx on food using gin (name gin_trgm_ops)")
    op.execute("create index food_core_name_trgm_plain_idx on food using gin (name gin_trgm_ops) "
               "where layer = 'core'")
    op.execute("create index food_name_name_trgm_plain_idx on food_name using gin (name gin_trgm_ops)")
    op.drop_index("food_name_trgm_idx", "food")
    op.drop_index("food_core_name_trgm_idx", "food")
    op.drop_index("food_name_name_trgm_idx", "food_name")
    op.execute("alter index food_name_trgm_plain_idx rename to food_name_trgm_idx")
    op.execute("alter index food_core_name_trgm_plain_idx rename to food_core_name_trgm_idx")
    op.execute("alter index food_name_name_trgm_plain_idx rename to food_name_name_trgm_idx")
    op.execute("drop function f_unaccent(text)")
