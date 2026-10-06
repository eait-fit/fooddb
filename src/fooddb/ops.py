"""What the admin panel pages read and the actions they run: overview counts, the job queue, the request log
statistics, accounts with their keys. Every action records who did it in `admin_action`."""

import json
import logging

from sqlalchemy import text

from fooddb import dump, health, jobs, requestlog
from fooddb.db import engine

log = logging.getLogger(__name__)
WINDOWS = {24: "hour", 168: "day", 720: "day"}  # hours shown on the Requests page, and the bucket of its chart
MAX_GRANT = 10_000_000
_P = "percentile_cont({}) within group (order by latency_ms)"
_STATS = f"count(*) n, count(*) filter (where status >= 400) errors, coalesce({_P.format(0.5)}, 0) p50, coalesce({_P.format(0.95)}, 0) p95"


def _rows(sql: str, **params) -> list[dict]:
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def _bars(rows: list[dict], key: str = "n") -> list[dict]:
    top = max((r[key] for r in rows), default=0) or 1
    return [r | {"pct": round(r[key] * 100 / top)} for r in rows]


def overview() -> dict:
    with engine().connect() as conn:

        def one(sql: str):
            return conn.execute(text(sql)).scalar_one()

        foods = [dict(r) for r in conn.execute(text("select layer, source, count(*) n from food group by 1, 2 order by 1, 2")).mappings()]
        sold = [dict(r) for r in conn.execute(text(
            "select currency, count(*) purchases, sum(credits) credits, sum(amount_cents) cents from purchase group by 1")).mappings()]
        snap = conn.execute(text("select day, built_at, products from snapshot order by day desc limit 1")).mappings().first()
        out = {
            "foods": _bars(foods), "products": one("select count(*) from product where merged_into is null"),
            "pending": one("select count(*) from observation where status = 'pending'"),
            "snapshot": dict(snap) if snap else None, "credits_sold": sum(r["credits"] for r in sold),
            "revenue": ", ".join(f"{r['currency'].upper()} {r['cents'] / 100:.2f}" for r in sold),
            "accounts": one("select count(*) from account"), "outstanding": one("select coalesce(sum(credits), 0) from account"),
            "metered_month": one("select coalesce(sum(requests), 0) from usage_month where month = date_trunc('month', now() at time zone 'utc')::date"),
            "metered_total": one("select coalesce(sum(requests), 0) from usage_month"),
            "requests": dict(conn.execute(text(f"select {_STATS} from request_log where at > now() - interval '24 hours'")).mappings().one()),
            "actions": [dict(r) for r in conn.execute(text("select at, \"by\", action, detail from admin_action order by id desc limit 15")).mappings()],
        }
    out["dump"] = (dump.manifests() or [None])[0]
    out["health"] = health.report()
    return out


def jobs_report() -> dict:
    return {
        "counts": {r["status"]: r["n"] for r in _rows("select lower(status::text) status, count(*) n from pq_tasks group by 1")},
        "tasks": _rows("""
            (select id, name, lower(status::text) status, attempts, run_at, started_at, completed_at, error, payload->'kwargs' kwargs
             from pq_tasks where status in ('PENDING', 'RUNNING') order by run_at limit 50)
            union all
            (select id, name, lower(status::text), attempts, run_at, started_at, completed_at, error, payload->'kwargs'
             from pq_tasks where status = 'FAILED' order by completed_at desc nulls last limit 50)
            union all
            (select id, name, lower(status::text), attempts, run_at, started_at, completed_at, error, payload->'kwargs'
             from pq_tasks where status = 'COMPLETED' order by completed_at desc limit 20)"""),
        "periodic": _rows("select name, key, cron, run_every, next_run, last_run, active from pq_periodic order by next_run"),
        "runs": _rows("""select fetcher, ref, status, foods, observations, error, started_at, finished_at
                         from fetch_run order by id desc limit 30"""),
        "health": health.report(),
    }


def requests_report(hours: int) -> dict:
    hours = hours if hours in WINDOWS else 24
    w = {"h": hours}
    since = "at > now() - make_interval(hours => :h)"
    totals = _rows(f"""select {_STATS},
                              count(*) filter (where status between 500 and 599) s5xx, count(*) filter (where status between 400 and 499) s4xx,
                              count(*) filter (where status = 402) s402, count(*) filter (where status = 429) s429
                       from request_log where {since}""", **w)[0]
    return {
        "hours": hours, "windows": list(WINDOWS), "days": requestlog.retention_days(), "totals": totals,
        "buckets": _bars(_rows(f"""select date_trunc('{WINDOWS[hours]}', at) b, count(*) n, count(*) filter (where status >= 400) errors
                                   from request_log where {since} group by 1 order by 1""", **w)),
        "statuses": _bars(_rows(f"select status, count(*) n from request_log where {since} group by 1 order by 2 desc", **w)),
        "callers": _bars(_rows(f"""select coalesce(key_name, '(refused or no key)') name, account_id, {_STATS}
                                   from request_log where {since} group by 1, 2 order by n desc limit 20""", **w)),
        "routes": _bars(_rows(f"select method, route, {_STATS} from request_log where {since} group by 1, 2 order by n desc limit 20", **w)),
        "recent": _rows("select at, method, route, status, latency_ms, bytes, key_name, account_id, ip_hash from request_log order by id desc limit 50"),
    }


def users_report(q: str = "") -> dict:
    q = q.strip().lower()[:100]
    accounts = _rows("""
        select a.id, a.email, a.credits, a.unlimited, a.created_at,
               coalesce((select requests from usage_month u where u.account_id = a.id
                         and u.month = date_trunc('month', now() at time zone 'utc')::date), 0) used,
               (select count(*) from purchase p where p.account_id = a.id) purchases,
               (select coalesce(sum(credits), 0) from purchase p where p.account_id = a.id) bought
        from account a where :q = '' or position(:q in a.email) > 0 order by a.id desc limit 100""", q=q)
    by_account: dict = {}
    for k in _rows("select id, name, scopes, account_id, created_at, last_used_at, revoked_at from api_key order by id"):
        by_account.setdefault(k["account_id"], []).append(k)
    return {"q": q, "accounts": [a | {"api_keys": by_account.get(a["id"], [])} for a in accounts],
            "total": _rows("select count(*) n from account")[0]["n"], "service_keys": by_account.get(None, [])}


def audit(conn, by: str, action: str, detail: dict) -> None:
    conn.execute(text('insert into admin_action ("by", action, detail) values (:by, :a, :d)'),
                 {"by": by, "a": action, "d": json.dumps(detail)})
    log.info("admin %s: %s %s", by, action, detail)


def grant_credits(account_id: int, credits: int, by: str) -> int:
    """Add credits to an account. Returns the new balance. LookupError: no such account."""
    if not 0 < credits <= MAX_GRANT:
        raise ValueError(f"credits must be between 1 and {MAX_GRANT}")
    with engine().begin() as conn:
        balance = conn.execute(text("update account set credits = credits + :n where id = :a returning credits"),
                               {"n": credits, "a": account_id}).scalar()
        if balance is None:
            raise LookupError(f"account {account_id} not found")
        audit(conn, by, "grant-credits", {"account": account_id, "credits": credits, "balance": balance})
    return balance


def set_unlimited(account_id: int, on: bool, by: str) -> None:
    with engine().begin() as conn:
        if conn.execute(text("update account set unlimited = :u where id = :a returning id"), {"u": on, "a": account_id}).scalar() is None:
            raise LookupError(f"account {account_id} not found")
        audit(conn, by, "set-unlimited", {"account": account_id, "unlimited": on})


def revoke_key(key_id: int, by: str) -> str | None:
    """Revoke an active key. Returns its name, or None when it is no active key."""
    with engine().begin() as conn:
        name = conn.execute(text("update api_key set revoked_at = now() where id = :k and revoked_at is null returning name"),
                            {"k": key_id}).scalar()
        if name is not None:
            audit(conn, by, "revoke-key", {"key": key_id, "name": name})
    return name


def _target(fetcher: str):
    if fetcher not in health.watched():
        raise ValueError(f"{fetcher} is not a fetcher that is switched on")
    if fetcher == "off-delta":
        return jobs.fetch_off_deltas, {}
    if fetcher == "snapshot":
        return jobs.build_snapshot, {}
    if fetcher.startswith("fdc-"):
        return jobs.fetch_fdc, {"dataset": fetcher.removeprefix("fdc-")}
    return jobs.fetch_table, {"source": fetcher}


def run_now(fetcher: str, by: str) -> int | None:
    """Queue one run of a fetcher or the snapshot build. Returns the task id, or None when the same run already waits.
    ValueError: not a watched fetcher."""
    fn, kwargs = _target(fetcher)
    with engine().connect() as conn:
        if conn.execute(text("select 1 from pq_tasks where name = :n and payload->'kwargs' = cast(:k as jsonb) "
                             "and status in ('PENDING', 'RUNNING')"), {"n": f"{fn.__module__}:{fn.__name__}", "k": json.dumps(kwargs)}).first():
            return None
    task = jobs.queue().enqueue(fn, **kwargs)
    with engine().begin() as conn:
        audit(conn, by, "run-now", {"fetcher": fetcher, "task": task})
    return task
