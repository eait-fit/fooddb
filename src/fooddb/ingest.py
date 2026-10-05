"""Shared write path for every fetcher: normalise, check, store observations."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice

from sqlalchemy import insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fooddb import checks
from fooddb.db import engine, fetch_run, food, observation

UNITS = {"ENERC_KCAL": "kcal", "NA": "mg"}  # everything else is grams
OBS_ROWS_PER_INSERT = 60_000 // len(observation.c)  # Postgres caps a statement at 65535 parameters


class EmptyRun(RuntimeError):
    """No record survived parsing: almost always a source schema change, never a quiet success."""


@dataclass
class Record:
    id: str
    source: str
    layer: str
    licence: str
    name: str
    observed_at: datetime
    values: dict[str, float]  # per 100 g or 100 ml (see basis), INFOODS tagname → value
    basis: str = "100g"  # "100g" | "100ml"
    gtin14: str | None = None
    brand: str | None = None
    lang: str | None = None
    serving_text: str | None = None
    serving_g: float | None = None
    extra_flags: list[str] = field(default_factory=list)


def already_done(fetcher: str, ref: str) -> bool:
    with engine().connect() as conn:
        return conn.execute(
            select(fetch_run.c.id).where(
                fetch_run.c.fetcher == fetcher, fetch_run.c.ref == ref, fetch_run.c.status == "done"
            )
        ).first() is not None


def done_refs(fetcher: str) -> set[str]:
    with engine().connect() as conn:
        return set(conn.execute(
            select(fetch_run.c.ref).where(fetch_run.c.fetcher == fetcher, fetch_run.c.status == "done")
        ).scalars())


def runs(fetcher: str, ref: str) -> list[dict]:
    """Run history for one fetcher and ref, oldest first."""
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(
            select(fetch_run).where(fetch_run.c.fetcher == fetcher, fetch_run.c.ref == ref).order_by(fetch_run.c.id)
        ).mappings()]


def run(fetcher: str, ref: str, records: Iterable[Record], batch: int = 500) -> tuple[int, int]:
    """Store records in batches; logs the run in fetch_run. Returns (foods, observations)."""
    with engine().begin() as conn:
        # A run still "running" for this ref was killed hard (pq timeout, OOM, SIGKILL): no handler
        # ran to close it. ponytail: assumes one worker; with several, check the run is stale first.
        conn.execute(update(fetch_run).where(
            fetch_run.c.fetcher == fetcher, fetch_run.c.ref == ref, fetch_run.c.status == "running",
        ).values(status="failed", error="abandoned: process ended without closing the run",
                 finished_at=datetime.now(UTC)))
        run_id = conn.execute(
            insert(fetch_run).values(fetcher=fetcher, ref=ref, status="running").returning(fetch_run.c.id)
        ).scalar_one()
    n_foods = n_obs = 0
    try:
        for chunk in _chunks(records, batch):
            f, o = _write(chunk)
            n_foods, n_obs = n_foods + f, n_obs + o
        if n_foods == 0:
            raise EmptyRun(f"{fetcher} {ref}: no records survived parsing")
    except BaseException as e:  # SystemExit/KeyboardInterrupt too (a bare SIGTERM is swept on the next run)
        _finish(run_id, "failed", n_foods, n_obs, repr(e))
        raise
    _finish(run_id, "done", n_foods, n_obs)
    return n_foods, n_obs


def _write(records: list[Record]) -> tuple[int, int]:
    latest_by_id = {r.id: r for r in sorted(records, key=lambda r: r.observed_at)}  # one per record id
    if not latest_by_id:
        return 0, 0
    with engine().begin() as conn:
        ids = list(latest_by_id)
        known = {row.id: row for row in conn.execute(
            select(food.c.id, food.c.product_id, food.c.source_updated_at).where(food.c.id.in_(ids)))}
        stored = {(row.food_id, row.nutrient): row for row in conn.execute(text(LATEST_SQL), {"ids": ids})}

        # A record seen for the first time becomes its own product; matching merges products later.
        new = [fid for fid in ids if fid not in known]
        pids = dict(zip(new, conn.execute(text(
            "insert into product (created_at) select now() from generate_series(1, :n) returning id"
        ), {"n": len(new)}).scalars().all())) if new else {}

        foods, obs = [], []
        for r in latest_by_id.values():
            failed = checks.flags(r.values)
            foods.append({
                "id": r.id, "product_id": known[r.id].product_id if r.id in known else pids[r.id],
                "source": r.source, "layer": r.layer, "licence": r.licence,
                "gtin14": r.gtin14, "name": r.name[:500], "brand": r.brand, "lang": r.lang,
                "serving_text": r.serving_text, "serving_g": r.serving_g,
                "flags": list(failed) + r.extra_flags, "source_updated_at": r.observed_at,
            })
            obs += _observations(r, failed, known.get(r.id), stored)

        stmt = pg_insert(food).values(foods)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=[food.c.id],
            set_={c: stmt.excluded[c] for c in (
                "gtin14", "name", "brand", "lang", "serving_text", "serving_g", "flags", "source_updated_at")}
            | {"fetched_at": datetime.now(UTC)},
            # A late or retried older file must not roll the row back to older metadata.
            where=food.c.source_updated_at <= stmt.excluded.source_updated_at,
        ))
        n_obs = 0
        for i in range(0, len(obs), OBS_ROWS_PER_INSERT):
            n_obs += len(conn.execute(
                pg_insert(observation).values(obs[i:i + OBS_ROWS_PER_INSERT])
                .on_conflict_do_nothing(constraint="observation_once").returning(observation.c.id)
            ).all())
    return len(foods), n_obs


# The newest stored observation per record and field, whatever its status.
LATEST_SQL = """
select distinct on (food_id, nutrient) food_id, nutrient, value_per_100, basis
from observation where food_id = any(:ids)
order by food_id, nutrient, observed_at desc, id desc
"""


def _observations(r: Record, failed: dict[str, set[str]], known, stored: dict) -> list[dict]:
    """Only what changed: new or different values, and fields the source has dropped (withdrawn,
    stored as null). A record older than what we already have adds nothing."""
    if known is not None and known.source_updated_at and r.observed_at < known.source_updated_at:
        return []
    changed = {k: v for k, v in r.values.items()
               if not ((last := stored.get((r.id, k))) and last.value_per_100 is not None
                       and float(last.value_per_100) == v and last.basis == r.basis)}
    dropped = {k: None for (fid, k), last in stored.items()
               if fid == r.id and last.value_per_100 is not None and k not in r.values}
    held = set().union(*failed.values())
    return [
        {"food_id": r.id, "nutrient": k, "value_per_100": v, "unit": UNITS.get(k, "g"), "basis": r.basis,
         "source": r.source, "licence": r.licence, "observed_at": r.observed_at,
         # A field a failed check implicates waits for review; its last accepted value keeps serving.
         "status": "pending" if k in held else "accepted"}
        for k, v in (changed | dropped).items()
    ]


def _finish(run_id: int, status: str, foods: int, obs: int, error: str | None = None) -> None:
    with engine().begin() as conn:
        conn.execute(update(fetch_run).where(fetch_run.c.id == run_id).values(
            status=status, foods=foods, observations=obs, error=error, finished_at=datetime.now(UTC)))


def _chunks(it: Iterable[Record], n: int) -> Iterator[list[Record]]:
    it = iter(it)
    while chunk := list(islice(it, n)):
        yield chunk
