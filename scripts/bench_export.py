"""Export throughput benchmark: seeds N synthetic products into this worktree's DEV database, builds a
snapshot, and times `export.lines` over it (products per second). Prints a SHA-256 of the output, so a
change that must stay byte-identical can be checked across runs.

    set -a; . ./.env.worktree; set +a; uv run python scripts/bench_export.py 20000 [--analyze] [--no-seed]

Default: yesterday's snapshot is built and analyzed first, then today's is built and left unanalyzed, as on
a database right after its nightly build (autovacuum has not run on the new day yet). `--analyze` also
analyzes snapshot_value after today's build. `--fresh` skips yesterday's snapshot: snapshot_value has the
statistics of the database it was seeded into (none, on a fresh one), as in the database suite.
`--no-seed` times the export only.

It TRUNCATES the data tables of the database in FOODDB__BACKEND__DATABASE_URL. It refuses a test
database and any non-local host.
"""

import hashlib
import sys
import time
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import text

from fooddb import export, snapshot
from fooddb.db import database_url, engine

NUTRIENTS = ("ENERC_KCAL", "PROCNT", "FAT", "CHOAVL", "SUGAR", "FIBTG", "NA", "FASAT")

# Every product has an OFF record with 8 nutrients; every 5th also has an FDC record with 5.
# `merged` extra products are merged into every 50th one after the build (see seed).
SEED = """
insert into product (id) select g from generate_series(1, :n + :merged) g;
insert into food (id, product_id, source, layer, licence, gtin14, name, brand, lang, category, flags, source_updated_at)
select 'off:' || g, g, 'off', 'off', 'ODbL-1.0', lpad(g::text, 14, '0'), 'Product ' || g, 'Brand ' || g % 500,
       'en', 'legumes', '{}', timestamptz '2026-01-01' + (g % 300) * interval '1 day'
from generate_series(1, :n + :merged) g;
insert into food (id, product_id, source, layer, licence, name, lang, category, flags, source_updated_at)
select 'fdc:' || g, g, 'fdc', 'core', 'CC0-1.0', 'Generic ' || g, 'en', 'legumes', '{}', timestamptz '2026-03-01'
from generate_series(1, :n, 5) g;
insert into observation (food_id, nutrient, value_per_100, unit, basis, source, licence, observed_at)
select 'off:' || g, n.name, 1 + (g * 7 + n.i * 13) % 400, case when n.name = 'ENERC_KCAL' then 'kcal' else 'g' end,
       '100g', 'off', 'ODbL-1.0', timestamptz '2026-02-01' + (g % 200) * interval '1 day'
from generate_series(1, :n + :merged) g, unnest(cast(:nutrients as text[])) with ordinality n(name, i);
insert into observation (food_id, nutrient, value_per_100, unit, basis, source, licence, observed_at)
select 'fdc:' || g, n.name, 1 + (g * 7 + n.i * 13 + (g % 3) * 20) % 400,
       case when n.name = 'ENERC_KCAL' then 'kcal' else 'g' end, '100g', 'fdc', 'CC0-1.0', timestamptz '2026-03-01'
from generate_series(1, :n, 5) g, unnest((cast(:nutrients as text[]))[1:5]) with ordinality n(name, i);
"""


def analyze(tables: str) -> None:
    with engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f"analyze {tables}"))


def seed(n: int, merged: int) -> None:
    with engine().begin() as conn:
        conn.execute(text("truncate food, observation, product, snapshot, snapshot_value restart identity cascade"))
        for stmt in SEED.split(";\n")[:-1]:
            conn.execute(text(stmt), {"n": n, "merged": merged, "nutrients": list(NUTRIENTS)})
    analyze("food, observation, product")  # a loaded database has these; the nightly build adds snapshot_value
    if "--fresh" not in sys.argv:  # yesterday's snapshot, analyzed: the statistics of a database that has run a night
        real_today = snapshot.today
        snapshot.today = lambda: real_today() - timedelta(days=1)
        snapshot.build()
        snapshot.today = real_today
        analyze("snapshot, snapshot_value")
    snapshot.build()
    if "--analyze" in sys.argv:
        analyze("snapshot_value")
    with engine().begin() as conn:  # a merge after the build: the old id's values stay frozen in the snapshot
        conn.execute(text("update food set product_id = (product_id - :n) * 50 where product_id > :n"), {"n": n})
        conn.execute(text("update product set merged_into = (id - :n) * 50 where id > :n"), {"n": n})


def main(n: int) -> None:
    url = urlparse(database_url())
    if url.hostname not in ("127.0.0.1", "localhost") or url.path.endswith("__test"):
        sys.exit(f"refusing to seed {url.path}: only a local, non-test dev database")
    merged = n // 50
    if "--no-seed" not in sys.argv:
        t = time.perf_counter()
        seed(n, merged)
        print(f"seeded {n} products (+{merged} merged away) in {time.perf_counter() - t:.1f}s")
    with engine().connect() as conn:
        day = conn.execute(text("select max(day) from snapshot")).scalar_one()
    sha, count = hashlib.sha256(), 0
    t = time.perf_counter()
    for line in export.lines(day, "off"):
        sha.update(line)
        count += 1
    dt = time.perf_counter() - t
    print(f"export: {count} products in {dt:.2f}s = {count / dt:.0f} products/s; sha256 {sha.hexdigest()}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20000)
