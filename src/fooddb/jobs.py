"""Async jobs on pq (Postgres-backed queue, same database). Each task runs in a forked child."""

from datetime import UTC, datetime, timedelta
from functools import cache

from loguru import logger
from pq import PQ, Priority
from pq.models import Task, TaskStatus
from sqlalchemy import select

from fooddb import health, requestlog
from fooddb.db import database_url
from fooddb.fetchers import bls, ciqual, cofid, fdc, fineli, frida, matvaretabellen, mext, off, tfda

TABLES = {m.FETCHER: m for m in (bls, ciqual, cofid, fineli, frida, matvaretabellen, mext, tfda)}  # national composition tables
WEEKLY = "0 3 * * 1"  # Monday 03:00 UTC
PRUNE_CRON = "15 3 * * *"
# FDC Branded is about 3 GB of JSON: it may run longer than the worker's default task limit.
# The OFF photo backfill waits 8 s between products (off.PAUSE_S): about 2 hours for the ~870 that matter on prod.
RUNTIME = {"fdc-branded": 6 * 3600, "off-images": 4 * 3600}


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


def backfill_off_images(limit: int | None = None) -> None:
    """One-off, not scheduled: photo references for the OFF records with pending values that have none yet. Safe to
    repeat: it takes only the records not yet checked."""
    off.backfill_images(limit=limit)


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


def build_recipes() -> None:
    from fooddb import recipes

    result = recipes.build()
    health.checked("recipes")
    logger.info(f"recipes: {result}")


def build_snapshot(full: bool = False) -> None:
    from fooddb import snapshot

    # Recipes recompute from their ingredients' current values before the build freezes: a changed
    # formulation or ingredient lands in the queue for review, and the accepted values serve tonight.
    try:
        build_recipes()
    except Exception as e:  # a recipe must never take the snapshot down: the build still runs
        logger.exception(f"recipes skipped: {e}")
    logger.info(f"snapshot: {snapshot.build(full=full)} products")


def dump_odbl() -> None:
    from fooddb import dump

    m = dump.write()
    logger.info("odbl dump: " + ("no snapshot yet" if m is None else f"{m['name']}, {m['products']} products"))


def prune_request_log() -> None:
    logger.info(f"request log: {requestlog.prune()} rows past {requestlog.retention_days()} days deleted")


def load_mt_names() -> None:
    from fooddb.names import load_mt

    logger.info(f"names mt: {load_mt()}")


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


def reap_orphans() -> int:
    """This one worker owns the queue: a task still RUNNING at boot was claimed by a worker that
    died before it could close the row — a deploy recreate SIGKILLs the old worker mid-drain, so
    the row outlives its run. A row an upsert parked a new version on is re-queued with it, the
    rest are failed. Runs before schedule(): once the rows are closed, this boot's upserts land
    as plain re-queues instead of parking on a dead run, so a bootstrap fetch killed by the
    deploy that added it runs again."""
    with queue().session() as session:
        orphans = list(session.execute(
            select(Task).where(Task.status == TaskStatus.RUNNING).with_for_update()
        ).scalars())
        for task in orphans:
            logger.warning(f"reaped orphaned task '{task.name}' (id={task.id}, started_at={task.started_at})"
                           + (": re-queued with the parked upsert" if task.requeue is not None else ": marked failed"))
            if task.requeue is not None:
                task.apply_requeue()
            else:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(UTC)
                task.error = "orphaned: the worker that claimed it ended without closing the task"
    return len(orphans)


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
    # The agent-written names ship with the code: BATCH lands the sync after the bootstrap fetches,
    # so a fresh install names the records once they exist and a redeploy resyncs the TSVs.
    q.upsert(load_mt_names, client_id="bootstrap-names-mt", priority=Priority.BATCH)
    # FDC and the national tables release a few times a year at most; a weekly check is plenty.
    for name, fn, kwargs in weekly:
        key = next(iter(kwargs.values()))
        if health.enabled(name):
            q.schedule(fn, cron=WEEKLY, priority=Priority.BATCH, key=key, max_runtime_seconds=RUNTIME.get(name), **kwargs)
        else:
            q.unschedule(fn, key=key)


def enqueue(name: str, **kwargs) -> int:
    fn = {"off": fetch_off_deltas, "off-dump": fetch_off_dump, "fdc": fetch_fdc, "table": fetch_table,
          "match": match_products, "snapshot": build_snapshot, "odbl-dump": dump_odbl,
          "off-images": backfill_off_images, "recipes": build_recipes}[name]
    return queue().enqueue(fn, max_runtime_seconds=RUNTIME.get(name), **kwargs)
