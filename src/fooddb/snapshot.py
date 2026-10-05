"""Nightly snapshot: every product's resolved values, frozen per day, for fast reads and pinning."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from fooddb.db import engine
from fooddb.resolve import values_sql

KEEP_DAYS = 30


def build(day: date | None = None) -> int:
    """(Re)build one day's snapshot in a single transaction and drop days past retention.
    Returns the number of products in it."""
    day = day or datetime.now(UTC).date()
    with engine().begin() as conn:
        conn.execute(text("delete from snapshot where day = :d"), {"d": day})
        conn.execute(text("insert into snapshot (day, products) values (:d, 0)"), {"d": day})
        for scope, layers in (("core", ["core"]), ("all", ["core", "off"])):
            conn.execute(text(f"""
                insert into snapshot_value (day, scope, product_id, nutrient, value_per_100, unit, basis,
                                            source, licence, observed_at)
                select :d, :scope, product_id, nutrient, value_per_100, unit, basis, source, licence, observed_at
                from ({values_sql("true")}) v
            """), {"d": day, "scope": scope, "layers": layers})
        n = conn.execute(text("select count(distinct product_id) from snapshot_value where day = :d and scope = 'all'"),
                         {"d": day}).scalar_one()
        conn.execute(text("update snapshot set products = :n where day = :d"), {"n": n, "d": day})
        conn.execute(text("delete from snapshot where day < :cutoff"), {"cutoff": day - timedelta(days=KEEP_DAYS)})
    return n


def predates(fetcher: str) -> bool:
    """True while no snapshot was built after the fetcher's first successful run."""
    with engine().connect() as conn:
        return conn.execute(text("""
            select 1 from snapshot where built_at > (
                select min(finished_at) from fetch_run where fetcher = :f and status = 'done')
        """), {"f": fetcher}).first() is None
