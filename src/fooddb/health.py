"""Health is freshness: each fetcher's last successful check against its schedule, and the age of
the snapshot the API serves. A process that is up but no longer fetching is not healthy."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from fooddb.db import engine

# Schedule plus slack. OFF deltas are checked every 6 h, FDC weekly, the snapshot nightly.
MAX_AGE = {
    "off-delta": timedelta(hours=12),
    "fdc-foundation": timedelta(days=8),
    "fdc-sr_legacy": timedelta(days=8),
    "snapshot": timedelta(hours=26),
}


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
    for name, max_age in MAX_AGE.items():
        at = last.get(name)
        fetchers[name] = {
            "last_ok": at.isoformat() if at else None,
            "max_age_hours": max_age.total_seconds() / 3600,
            "fresh": at is not None and now - at <= max_age,
        }
    return {"ok": all(f["fresh"] for f in fetchers.values()), "fetchers": fetchers}
