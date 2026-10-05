"""Async jobs on pq (Postgres-backed queue, same database). Each task runs in a forked child."""

from datetime import timedelta
from functools import cache

from loguru import logger
from pq import PQ, Priority

from fooddb import health
from fooddb.db import database_url
from fooddb.fetchers import fdc, off


@cache
def queue() -> PQ:
    return PQ(database_url())


def fetch_off_deltas(max_files: int = 1) -> None:
    done = off.fetch(max_files=max_files)
    health.checked(off.FETCHER)
    for name, foods, obs in done:
        logger.info(f"off delta {name}: {foods} foods, {obs} new observations")
    if done:
        _rematch()


def fetch_off_dump(force: bool = False) -> None:
    result = off.fetch_dump(force=force)
    if result is not None:
        _rematch()
    logger.info("off dump: " + ("already loaded" if result is None else f"{result[0]} foods, {result[1]} new observations"))


def fetch_fdc(dataset: str = "foundation", force: bool = False) -> None:
    result = fdc.fetch(dataset, force=force)
    health.checked(f"fdc-{dataset}")
    if result is not None:
        _rematch()
    logger.info(f"fdc {dataset}: " + ("already current" if result is None else f"{result[0]} foods, {result[1]} new observations"))


def match_products() -> None:
    # Imported in the forked task, never in the worker parent: DuckDB and pyarrow are not
    # fork-safe on macOS, and a parent that loaded them segfaults every child it forks.
    from fooddb import match

    logger.info(f"match: {match.run()} products merged")


def build_snapshot() -> None:
    from fooddb import snapshot

    logger.info(f"snapshot: {snapshot.build()} products")


def _rematch() -> None:
    """Queue one matching pass after new data; repeated calls collapse into one pending task."""
    queue().upsert(match_products, client_id="match-products")


def schedule() -> None:
    """Periodic fetches. Idempotent: re-registering updates the schedule."""
    q = queue()
    q.schedule(fetch_off_deltas, run_every=timedelta(hours=6))
    q.schedule(build_snapshot, cron="30 2 * * *")  # nightly: what the API serves the next day
    # A fresh install fills itself instead of waiting for the weekly cron: each source never
    # checked is fetched now, and a first snapshot follows (BATCH priority runs after the fetches).
    checked = {name for name, f in health.report()["fetchers"].items() if f["last_ok"]}
    for ds in fdc.DATASETS:
        if f"fdc-{ds}" not in checked:
            q.upsert(fetch_fdc, client_id=f"bootstrap-fdc-{ds}", dataset=ds)
    if "snapshot" not in checked:
        q.upsert(build_snapshot, client_id="bootstrap-snapshot", priority=Priority.BATCH)
    for ds in fdc.DATASETS:  # FDC releases twice a year; a weekly check is plenty
        q.schedule(fetch_fdc, cron="0 3 * * 1", priority=Priority.BATCH, key=ds, dataset=ds)


def enqueue(name: str, **kwargs) -> int:
    fn = {"off": fetch_off_deltas, "off-dump": fetch_off_dump, "fdc": fetch_fdc, "match": match_products,
          "snapshot": build_snapshot}[name]
    return queue().enqueue(fn, **kwargs)
