"""Stem-search indexes (#161): a snowball-stemmed lexeme vector per name, next to the trigram
indexes. A name's own language picks the config (food.lang / food_name.lang); a language
Postgres cannot stem keeps whole words under 'simple'. The tsvector goes through
f_stemtext(lang, name), an IMMUTABLE wrapper like f_unaccent (a CASE in an index expression
is refused). The stem fallback query runs only when the trigram path is empty, so the
indexes see mostly misses.

Revision ID: 0025
Revises: 0024
"""

from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    # Keep in sync with fooddb.stems.CONFIG — the query's expression must match the index's.
    op.execute(
        """create or replace function f_stemtext(text, text) returns tsvector
        language sql immutable parallel safe strict as
        $$ select to_tsvector((case $1
            when 'en' then 'english' when 'de' then 'german' when 'fr' then 'french'
            when 'es' then 'spanish' when 'ru' then 'russian' when 'uk' then 'russian'
            when 'nb' then 'norwegian' when 'no' then 'norwegian' when 'nn' then 'norwegian'
            when 'da' then 'danish' when 'sv' then 'swedish' when 'fi' then 'finnish'
            when 'it' then 'italian' when 'pt' then 'portuguese' when 'nl' then 'dutch'
            else 'simple' end)::regconfig, public.f_unaccent($2)) $$"""
    )
    op.execute("create index food_stem_idx on food using gin (f_stemtext(lang, name))")
    op.execute("create index food_name_name_stem_idx on food_name using gin (f_stemtext(lang, name))")


def downgrade() -> None:
    op.execute("drop index food_stem_idx")
    op.execute("drop index food_name_name_stem_idx")
    op.execute("drop function f_stemtext(text, text)")
