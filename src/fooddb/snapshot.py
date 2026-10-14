"""Nightly snapshot: every product's resolved values, frozen, for fast reads. One snapshot only,
the current one: each build replaces it inside the same transaction."""

from datetime import UTC, date, datetime

from sqlalchemy import text

from fooddb.db import engine
from fooddb.resolve import values_sql


def today() -> date:
    return datetime.now(UTC).date()


def build() -> int:
    """(Re)build today's snapshot in a single transaction and drop every other day. The one row in
    `snapshot` is the snapshot the API and the export serve. Returns the number of products in it."""
    day = today()
    with engine().begin() as conn:
        conn.execute(text("delete from snapshot where day = :d"), {"d": day})
        conn.execute(text("insert into snapshot (day, products) values (:d, 0)"), {"d": day})
        for scope, layers in (("core", ["core"]), ("all", ["core", "off"])):
            conn.execute(text(f"""
                insert into snapshot_value (day, scope, product_id, nutrient, value_per_100, unit, basis,
                                            source, licence, observed_at, approved)
                select :d, :scope, product_id, nutrient, value_per_100, unit, basis, source, licence, observed_at,
                       approved
                from ({values_sql("true")}) v
            """), {"d": day, "scope": scope, "layers": layers})
        n = conn.execute(text("select count(distinct product_id) from snapshot_value where day = :d and scope = 'all'"),
                         {"d": day}).scalar_one()
        conn.execute(text("update snapshot set products = :n where day = :d"), {"n": n, "d": day})
        # Only the current snapshot is kept: deleting the other days cascades their values away.
        conn.execute(text("delete from snapshot where day <> :d"), {"d": day})
        conn.execute(text("analyze snapshot_value"))  # autovacuum lags a night: until then no read knows the new day's size
    return n


def predates(fetcher: str) -> bool:
    """True while no snapshot was built after the fetcher's first successful run."""
    with engine().connect() as conn:
        return conn.execute(text("""
            select 1 from snapshot where built_at > (
                select min(finished_at) from fetch_run where fetcher = :f and status = 'done')
        """), {"f": fetcher}).first() is None
