"""Names a source does not state: `data/names/mt/<lang>.tsv` holds agent-written translations —
record_id, the record's name (for the reader), the name a speaker of <lang> would type. `load_mt`
syncs them into `food_name` as origin='mt', next to the source's own rows: a table refetch
restates only origin='source', so these survive it. A line gone from a TSV drops its row; a line
for a record we do not hold is skipped.

Search needs no knowledge of any of this — it already unions food_name."""

from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fooddb.db import engine, food, food_name

# Repo root in a checkout, /app in the image (the Dockerfile copies data/ in).
MT_DIR = Path(__file__).resolve().parents[2] / "data" / "names" / "mt"


def _tsv(f: Path) -> dict[str, str]:
    """{record_id: name} of one `record_id TAB record's name TAB translation` file."""
    rows = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        if not (line := line.strip()) or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 3 and (rid := cols[0].strip()) and (name := cols[2].strip()):
            rows[rid] = name[:500]
    return rows


def load_mt(dir: Path = MT_DIR) -> dict[str, int]:
    """Sync every `<lang>.tsv` into food_name: {lang: rows held}. Idempotent — reruns rewrite nothing."""
    out = {}
    for f in sorted(dir.glob("*.tsv")):
        lang, rows = f.stem, _tsv(f)
        with engine().begin() as conn:
            # A TSV may still name a record a refetch retired (or one a smaller database never had):
            # its row is not loadable, and a retired record's rows cascade away anyway.
            live = set(conn.execute(select(food.c.id).where(food.c.id.in_(list(rows)))).scalars())
            conn.execute(food_name.delete().where(food_name.c.origin == "mt", food_name.c.lang == lang,
                                                  ~food_name.c.food_id.in_(list(rows))))
            if vals := [{"food_id": rid, "lang": lang, "name": n, "origin": "mt"}
                        for rid, n in rows.items() if rid in live]:
                stmt = pg_insert(food_name).values(vals)
                conn.execute(stmt.on_conflict_do_update(index_elements=["food_id", "lang", "origin"],
                                                        set_={"name": stmt.excluded.name}))
        out[lang] = len(vals)
        logger.info(f"names mt {lang}: {len(vals)} rows ({len(rows) - len(vals)} for records not held)")
    return out
