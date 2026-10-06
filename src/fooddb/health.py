"""Health is freshness: each fetcher's last successful check against its schedule, and the age of
the snapshot the API serves. A process that is up but no longer fetching is not healthy."""

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from fooddb.db import engine

# Schedule plus slack. OFF deltas are checked every 6 h, FDC and the national tables weekly, the snapshot nightly.
MAX_AGE = {
    "off-delta": timedelta(hours=12),
    "fdc-foundation": timedelta(days=8),
    "fdc-sr_legacy": timedelta(days=8),
    "fdc-branded": timedelta(days=8),
    "ciqual": timedelta(days=8),
    "cofid": timedelta(days=8),
    "fineli": timedelta(days=8),
    "frida": timedelta(days=8),
    "matvaretabellen": timedelta(days=8),
    "mext": timedelta(days=8),
    "tfda": timedelta(days=8),
    "snapshot": timedelta(hours=26),
}
# Fetchers that run only when switched on. FDC Branded is about 3 GB of JSON. Fineli's site refuses
# automated downloads behind a Cloudflare challenge (2026-10-06), so it needs a reachable mirror.
OPTIONAL = {"fdc-branded": "FOODDB__BACKEND__FETCH_FDC_BRANDED", "fineli": "FOODDB__BACKEND__FETCH_FINELI"}


def enabled(fetcher: str) -> bool:
    return fetcher not in OPTIONAL or os.environ.get(OPTIONAL[fetcher], "false").lower() == "true"


def watched() -> list[str]:
    """What /healthz watches: every fetcher that is switched on, and the snapshot."""
    return [name for name in MAX_AGE if enabled(name)]


def checked(fetcher: str, at: datetime | None = None) -> None:
    """Record a successful check, including one that found nothing new."""
    with engine().begin() as conn:
        conn.execute(text("""
            insert into fetcher_check (fetcher, checked_at) values (:f, :at)
            on conflict (fetcher) do update set checked_at = excluded.checked_at
        """), {"f": fetcher, "at": at or datetime.now(UTC)})


def report(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    with engine().connect() as conn:
        last = dict(conn.execute(text("select fetcher, checked_at from fetcher_check")).all())
        last["snapshot"] = conn.execute(text("select max(built_at) from snapshot")).scalar_one()
    fetchers = {}
    for name in watched():
        at, max_age = last.get(name), MAX_AGE[name]
        fetchers[name] = {
            "last_ok": at.isoformat() if at else None,
            "max_age_hours": max_age.total_seconds() / 3600,
            "fresh": at is not None and now - at <= max_age,
        }
    return {"ok": all(f["fresh"] for f in fetchers.values()), "fetchers": fetchers}
