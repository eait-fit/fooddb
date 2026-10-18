"""Nightly snapshot: every product's resolved values, frozen, for fast reads. One snapshot only,
the current one. Each build rewrites only the products whose resolved values can differ since the
last build — the `snapshot_dirty` set that statement-level triggers on `observation`, `food` and
`product` keep, plus both ends of every `merge_log` row since the last `built_at` — all inside the
same transaction. `full` rewrites every product, and is what runs while no snapshot exists."""

import time
from datetime import UTC, date, datetime

from loguru import logger
from sqlalchemy import Connection, text

from fooddb.db import engine
from fooddb.resolve import values_sql


def today() -> date:
    return datetime.now(UTC).date()


def changed(conn: Connection, since: datetime) -> list[int]:
    """The products whose resolved values can differ since `since`. The dirty set covers every
    write path, including deletes and review undo (no timestamp survives either); `merge_log`
    covers any merge or split the triggers did not see."""
    return sorted(conn.execute(text("""
        with drained as (delete from snapshot_dirty returning product_id)
        select product_id from drained
        union select from_product from merge_log where at > :since
        union select into_product from merge_log where at > :since
    """), {"since": since}).scalars())


def build(full: bool = False) -> int:
    """(Re)build the snapshot in a single transaction and return the number of products in it.

    With `full`, or while no snapshot exists, every product is rewritten. Otherwise only the
    products that `changed` collects are deleted and resolved again, in both scopes. The one row
    in `snapshot` is what the API, the export and freshness checks read; `day` and `built_at`
    always move to this build."""
    day = today()
    started = time.monotonic()
    with engine().begin() as conn:
        current = conn.execute(text("select day, built_at, products from snapshot")).mappings().first()
        pids = None if full or current is None else changed(conn, current["built_at"])
        if pids is not None and len(pids) * 2 > conn.execute(text("select count(*) from product")).scalar_one():
            pids = None  # half the catalog changed: a full rewrite beats per-product lookups
        if pids is None:
            conn.execute(text("delete from snapshot_dirty"))
            conn.execute(text("delete from snapshot_value"))
        elif pids:
            conn.execute(text("delete from snapshot_value where product_id = any(:pids)"), {"pids": pids})
        if pids is None or pids:
            where, params = ("true", {}) if pids is None else ("f.product_id = any(:pids)", {"pids": pids})
            for scope, layers in (("core", ["core"]), ("all", ["core", "off"])):
                conn.execute(text(f"""
                    insert into snapshot_value (scope, product_id, nutrient, value_per_100, unit, basis,
                                                source, licence, observed_at, approved)
                    select :scope, product_id, nutrient, value_per_100, unit, basis, source, licence, observed_at,
                           approved
                    from ({values_sql(where)}) v
                """), params | {"scope": scope, "layers": layers})
            n = conn.execute(text("select count(distinct product_id) from snapshot_value"
                                  " where scope = 'all'")).scalar_one()
            conn.execute(text("analyze snapshot_value"))  # autovacuum lags a night: until then no read knows the new size
        else:
            n = current["products"]
        if current is None:
            conn.execute(text("insert into snapshot (day, products) values (:d, :n)"), {"d": day, "n": n})
        else:
            conn.execute(text("update snapshot set day = :d, built_at = now(), products = :n"),
                         {"d": day, "n": n})
    kind = "full" if pids is None else "incremental"
    logger.info(f"snapshot ({kind}): {n} products, "
                f"{len(pids) if pids is not None else n} changed, in {time.monotonic() - started:.1f}s")
    return n


def predates(fetcher: str) -> bool:
    """True while no snapshot was built after the fetcher's first successful run."""
    with engine().connect() as conn:
        return conn.execute(text("""
            select 1 from snapshot where built_at > (
                select min(finished_at) from fetch_run where fetcher = :f and status = 'done')
        """), {"f": fetcher}).first() is None
