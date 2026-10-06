"""The request log: one `request_log` row per API request, written from this one ASGI middleware. A row holds the
route template (`/v1/products/{barcode}`, never the raw URL or query), the caller, the status, the latency and the
response size. The client address is kept only as an 8-hex-digit HMAC under FOODDB__BACKEND__SECRET_KEY, to tell
callers apart for abuse; with no secret it is not kept. Health probes and /admin are not logged."""

import hashlib
import hmac
import logging
import os
import time

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from fooddb.db import engine

log = logging.getLogger(__name__)
SKIPPED = ("/livez", "/healthz", "/admin")
UNMATCHED = "(unmatched)"


def retention_days() -> int:
    return int(os.environ.get("FOODDB__BACKEND__REQUEST_LOG_DAYS", "30"))


def prune() -> int:
    """Delete the rows older than the retention. Returns how many."""
    with engine().begin() as conn:
        return conn.execute(text("delete from request_log where at < now() - make_interval(days => :d)"),
                            {"d": retention_days()}).rowcount


def ip_hash(ip: str | None) -> str | None:
    secret = os.environ.get("FOODDB__BACKEND__SECRET_KEY")
    if not secret or not ip:
        return None
    return hmac.new(secret.encode(), b"request-log-ip:" + ip.encode(), hashlib.sha256).hexdigest()[:8]


def _insert(row: dict) -> None:
    with engine().begin() as conn:
        conn.execute(text("""
            insert into request_log (method, route, status, latency_ms, bytes, key_id, key_name, account_id, ip_hash)
            values (:method, :route, :status, :latency_ms, :bytes, :key_id, :key_name, :account_id, :ip_hash)
        """), row)


async def _record(scope: dict, status: int, size: int, started: float) -> None:
    caller = scope.get("state", {}).get("caller")  # set by auth.authenticate; absent when no key check ran or the key was refused
    client = scope.get("client")
    row = {"method": scope["method"], "route": getattr(scope.get("route"), "path", None) or UNMATCHED, "status": status,
           "latency_ms": round((time.perf_counter() - started) * 1000), "bytes": size,
           "key_id": caller.key_id if caller else None, "key_name": caller.name if caller else None,
           "account_id": caller.account_id if caller else None, "ip_hash": ip_hash(client[0] if client else None)}
    try:
        await run_in_threadpool(_insert, row)  # after the response went out: the client does not wait for it
    except Exception as e:
        log.warning("request log insert failed: %s", type(e).__name__)


class RequestLog:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or any(path == p or path.startswith(p + "/") for p in SKIPPED):
            return await self.app(scope, receive, send)
        started, status, size = time.perf_counter(), 500, 0

        async def sending(message):
            nonlocal status, size
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, sending)
        finally:
            await _record(scope, status, size, started)
