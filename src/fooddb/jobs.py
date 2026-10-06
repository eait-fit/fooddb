"""Async jobs on pq (Postgres-backed queue, same database). Each task runs in a forked child."""

from datetime import timedelta
from functools import cache

from loguru import logger
from pq import PQ, Priority

from fooddb import health, requestlog
from fooddb.db import database_url
from fooddb.fetchers import ciqual, cofid, fdc, fineli, frida, matvaretabellen, mext, off, tfda

TABLES = {m.FETCHER: m for m in (ciqual, cofid, fineli, frida, matvaretabellen, mext, tfda)}  # national composition tables
WEEKLY = "0 3 * * 1"  # Monday 03:00 UTC
PRUNE_CRON = "15 3 * * *"
# FDC Branded is about 3 GB of JSON: it may run longer than the worker's default task limit.
RUNTIME = {"fdc-branded": 6 * 3600}


@cache
def queue() -> PQ:
    return PQ(database_url())


def fetch_off_deltas(max_files: int = 1) -> None:
    done = off.fetch(max_files=max_files)
    health.checked(off.FETCHER)
    for name, foods, obs in done:
        logger.info(f"off delta {name}: {foods} foods, {obs} new observations")
    if done:
        _rematch(off.FETCHER)


def fetch_off_dump(force: bool = False) -> None:
    result = off.fetch_dump(force=force)
    if result is not None:
        _rematch(off.DUMP_FETCHER)
    logger.info("off dump: " + ("already loaded" if result is None else f"{result[0]} foods, {result[1]} new observations"))


def fetch_fdc(dataset: str = "foundation", force: bool = False) -> None:
    result = fdc.fetch(dataset, force=force)
    health.checked(f"fdc-{dataset}")
    if result is not None:
        _rematch(f"fdc-{dataset}")
    logger.info(f"fdc {dataset}: " + ("already current" if result is None else f"{result[0]} foods, {result[1]} new observations"))


def fetch_table(source: str, force: bool = False) -> None:
    result = TABLES[source].fetch(force=force)
    health.checked(source)
    if result is not None:
        _rematch(source)
    logger.info(f"{source}: " + ("already current" if result is None else f"{result[0]} foods, {result[1]} new observations"))


def match_products() -> None:
    # Imported in the forked task, never in the worker parent: DuckDB and pyarrow are not
    # fork-safe on macOS, and a parent that loaded them segfaults every child it forks.
    from fooddb import match

    logger.info(f"match: {match.run()} products merged")


def build_snapshot() -> None:
    from fooddb import snapshot

    logger.info(f"snapshot: {snapshot.build()} products")


def dump_odbl() -> None:
    from fooddb import dump

    m = dump.write()
    logger.info("odbl dump: " + ("no final snapshot yet" if m is None else f"{m['name']}, {m['products']} products"))


def prune_request_log() -> None:
    logger.info(f"request log: {requestlog.prune()} rows past {requestlog.retention_days()} days deleted")


def read_label(photo: str, hints: dict[str, str], read: str | None = None) -> None:
    from fooddb.labels import intake

    logger.info(f"label read: {intake.process(photo, hints, read)}")
    _rematch(intake.FETCHER)


def _rematch(fetcher: str) -> None:
    """Queue one matching pass after new data; repeated calls collapse into one pending task.
    A fetcher's first data also queues a snapshot rebuild, so a fresh install serves every source
    before the nightly build. BATCH priority runs it after the matching pass."""
    from fooddb import snapshot

    queue().upsert(match_products, client_id="match-products")
    if snapshot.predates(fetcher):
        queue().upsert(build_snapshot, client_id="bootstrap-snapshot", priority=Priority.BATCH)


def schedule() -> None:
    """Periodic fetches. Idempotent: re-registering updates the schedule."""
    q = queue()
    q.schedule(fetch_off_deltas, run_every=timedelta(hours=6))
    q.schedule(build_snapshot, cron="30 2 * * *")  # nightly: what the API serves the next day
    q.schedule(dump_odbl, cron="0 4 1 * *", priority=Priority.BATCH)  # monthly ODbL dump of the OFF layer
    q.schedule(prune_request_log, cron=PRUNE_CRON, priority=Priority.BATCH)
    # A fresh install fills itself instead of waiting for the weekly cron: each source never
    # checked is fetched now, and a first snapshot follows (BATCH priority runs after the fetches).
    # A source switched off (health.OPTIONAL) is neither fetched nor scheduled.
    checked = {name for name, f in health.report()["fetchers"].items() if f["last_ok"]}
    weekly = [(f"fdc-{ds}", fetch_fdc, {"dataset": ds}) for ds in fdc.DATASETS]
    weekly += [(name, fetch_table, {"source": name}) for name in TABLES]
    for name, fn, kwargs in weekly:
        if health.enabled(name) and name not in checked:
            q.upsert(fn, client_id=f"bootstrap-{name}", max_runtime_seconds=RUNTIME.get(name), **kwargs)
    if "snapshot" not in checked:
        q.upsert(build_snapshot, client_id="bootstrap-snapshot", priority=Priority.BATCH)
    # FDC and the national tables release a few times a year at most; a weekly check is plenty.
    for name, fn, kwargs in weekly:
        key = next(iter(kwargs.values()))
        if health.enabled(name):
            q.schedule(fn, cron=WEEKLY, priority=Priority.BATCH, key=key, max_runtime_seconds=RUNTIME.get(name), **kwargs)
        else:
            q.unschedule(fn, key=key)


def enqueue(name: str, **kwargs) -> int:
    fn = {"off": fetch_off_deltas, "off-dump": fetch_off_dump, "fdc": fetch_fdc, "table": fetch_table,
          "match": match_products, "snapshot": build_snapshot, "odbl-dump": dump_odbl}[name]
    return queue().enqueue(fn, **kwargs)
