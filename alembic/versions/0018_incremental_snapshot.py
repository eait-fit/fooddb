"""Incremental snapshot builds: snapshot_value drops the day key, and snapshot_dirty collects the
products a change touched.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"

# One snapshot exists, so snapshot_value.day carried the same value in every row and updating the
# snapshot's day would have had to cascade to millions of rows. The build now rewrites only the
# products in snapshot_dirty (plus both ends of recent merge_log rows), in the same transaction.
# A trigger on each table whose writes can move a resolved value appends the product ids it
# touched — observation (new values, withdrawals, review decisions, undo), food (a record moving
# product or layer, or deleted) and product (merged_into, deleted). Triggers, not timestamps: an
# undo clears reviewed_at and a delete leaves no row to stamp. observation writes come in bulk,
# so they pay once per statement; food and product moves are rare and pay per row.
FUNCTION = """
create or replace function snapshot_dirty_mark() returns trigger language plpgsql as $$
begin
    if tg_op <> 'DELETE' then
        insert into snapshot_dirty (product_id)
        select f.product_id from new_rows n join food f on f.id = n.food_id
        on conflict do nothing;
    end if;
    if tg_op <> 'INSERT' then
        insert into snapshot_dirty (product_id)
        select f.product_id from old_rows n join food f on f.id = n.food_id
        on conflict do nothing;
    end if;
    return null;
end $$;
"""

ROW_FUNCTION = """
create or replace function snapshot_dirty_mark_row() returns trigger language plpgsql as $$
begin
    if tg_table_name = 'food' then
        insert into snapshot_dirty (product_id) values (old.product_id) on conflict do nothing;
        if tg_op <> 'DELETE' then
            insert into snapshot_dirty (product_id) values (new.product_id) on conflict do nothing;
        end if;
    else  -- product
        insert into snapshot_dirty (product_id) values (old.id) on conflict do nothing;
    end if;
    return null;
end $$;
"""

TRIGGERS = [
    """create trigger snapshot_dirty_obs_i after insert on observation
       referencing new table as new_rows
       for each statement execute function snapshot_dirty_mark()""",
    """create trigger snapshot_dirty_obs_u after update on observation
       referencing old table as old_rows new table as new_rows
       for each statement execute function snapshot_dirty_mark()""",
    """create trigger snapshot_dirty_obs_d after delete on observation
       referencing old table as old_rows
       for each statement execute function snapshot_dirty_mark()""",
    """create trigger snapshot_dirty_food_u after update of product_id, layer on food
       for each row execute function snapshot_dirty_mark_row()""",
    """create trigger snapshot_dirty_food_d after delete on food
       for each row execute function snapshot_dirty_mark_row()""",
    """create trigger snapshot_dirty_product_u after update of merged_into on product
       for each row execute function snapshot_dirty_mark_row()""",
    """create trigger snapshot_dirty_product_d after delete on product
       for each row execute function snapshot_dirty_mark_row()""",
]


def upgrade() -> None:
    op.drop_column("snapshot_value", "day")  # drops the day-leading primary key and its cascade FK
    op.create_primary_key("snapshot_value_pkey", "snapshot_value", ["scope", "product_id", "nutrient"])
    op.create_table("snapshot_dirty", sa.Column("product_id", sa.BigInteger, primary_key=True))
    op.execute(FUNCTION)
    op.execute(ROW_FUNCTION)
    for ddl in TRIGGERS:
        op.execute(ddl)
    # The triggers saw nothing before this migration: the first incremental build replays every
    # product once, like a full build, and nothing changed meanwhile is missed.
    op.execute("insert into snapshot_dirty select id from product")


def downgrade() -> None:
    for stmt in (
        "drop trigger snapshot_dirty_obs_i on observation",
        "drop trigger snapshot_dirty_obs_u on observation",
        "drop trigger snapshot_dirty_obs_d on observation",
        "drop trigger snapshot_dirty_food_u on food",
        "drop trigger snapshot_dirty_food_d on food",
        "drop trigger snapshot_dirty_product_u on product",
        "drop trigger snapshot_dirty_product_d on product",
        "drop function snapshot_dirty_mark()",
        "drop function snapshot_dirty_mark_row()",
        "drop table snapshot_dirty",
        "alter table snapshot_value add column day date",
        "update snapshot_value set day = (select day from snapshot)",
        "alter table snapshot_value alter column day set not null",
        "alter table snapshot_value add primary key (day, scope, product_id, nutrient)",
        "alter table snapshot_value add foreign key (day) references snapshot (day) on delete cascade",
    ):
        op.execute(stmt)
