"""API keys, scopes and rate limits. REST routes, the MCP route and the admin login all check
callers here. A key is stored as its SHA-256 hash only: the token is shown once, at creation."""

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from fooddb.db import engine

IMPLIES = {"read": {"read"}, "review": {"read", "review"}, "admin": {"read", "review", "admin"}}


@dataclass(frozen=True)
class Caller:
    name: str
    scopes: frozenset[str]
    bucket: str | None  # rate-limit counter; None: not limited here
    limit: int
    key_id: int | None = None


ANONYMOUS_NAME = "anonymous"


def _default_limit() -> int:
    return int(os.environ.get("FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE", "60"))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _caller(row) -> Caller:
    scopes = frozenset().union(*(IMPLIES[s] for s in row["scopes"]))
    return Caller(row["name"], scopes, f"key:{row['id']}", row["rate_limit"] or _default_limit(), row["id"])


def create(name: str, scopes: list[str], rate_limit: int | None = None) -> str:
    if not scopes or not set(scopes) <= IMPLIES.keys():
        raise ValueError(f"scopes must be some of {', '.join(IMPLIES)}")
    token = "fdb_" + secrets.token_urlsafe(32)
    with engine().begin() as conn:
        conn.execute(text("insert into api_key (name, token_hash, scopes, rate_limit) values (:n, :h, :s, :r)"),
                     {"n": name, "h": _hash(token), "s": sorted(set(scopes)), "r": rate_limit})
    return token


def keys() -> list[dict]:
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "select id, name, scopes, rate_limit, created_at, last_used_at, revoked_at from api_key order by id"
        )).mappings()]


def revoke(name: str) -> bool:
    with engine().begin() as conn:
        return conn.execute(text("update api_key set revoked_at = now() where name = :n and revoked_at is null"),
                            {"n": name}).rowcount > 0


def lookup(token: str) -> Caller | None:
    """The active key for this token, marked as used now."""
    with engine().begin() as conn:
        row = conn.execute(text("""
            update api_key set last_used_at = now() where token_hash = :h and revoked_at is null
            returning id, name, scopes, rate_limit
        """), {"h": _hash(token)}).mappings().first()
    return _caller(row) if row else None


def by_id(key_id: int) -> Caller | None:
    with engine().connect() as conn:
        row = conn.execute(text("select id, name, scopes, rate_limit from api_key where id = :id and revoked_at is null"),
                           {"id": key_id}).mappings().first()
    return _caller(row) if row else None


def authenticate(request: Request) -> Caller:
    """A presented key must be valid; without one, a matching RapidAPI proxy secret reads, else anonymous."""
    h = request.headers
    token = h.get("x-api-key") or (h.get("authorization", "").removeprefix("Bearer ").strip() or None)
    if token:
        if (caller := lookup(token)) is None:
            raise HTTPException(401, "invalid or revoked API key", {"WWW-Authenticate": "Bearer"})
        return caller
    proxy = os.environ.get("FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET")
    sent = h.get("x-rapidapi-proxy-secret")
    if proxy and sent and hmac.compare_digest(sent.encode(), proxy.encode()):
        return Caller("rapidapi", frozenset({"read"}), None, 0)  # RapidAPI meters its own customers
    ip = request.client.host if request.client else "unknown"
    return Caller(ANONYMOUS_NAME, frozenset(), f"ip:{ip}", _default_limit())


def authorize(caller: Caller, scope: str) -> None:
    anonymous_read = (scope == "read" and caller.name == ANONYMOUS_NAME and
                      os.environ.get("FOODDB__BACKEND__REQUIRE_KEY_FOR_READS", "").lower() not in ("1", "true", "yes"))
    if scope not in caller.scopes and not anonymous_read:
        if caller.name == ANONYMOUS_NAME:
            raise HTTPException(401, f"an API key with the {scope} scope is required", {"WWW-Authenticate": "Bearer"})
        raise HTTPException(403, f"this API key lacks the {scope} scope")
    if caller.bucket is not None:
        _count(caller)


def _count(caller: Caller) -> None:
    """Fixed one-minute window, one upsert per request, shared by every API replica."""
    with engine().begin() as conn:
        hits, retry_after = conn.execute(text("""
            insert into rate_limit (bucket, window_start, hits) values (:b, date_trunc('minute', now()), 1)
            on conflict (bucket) do update set
                hits = case when rate_limit.window_start = excluded.window_start then rate_limit.hits + 1 else 1 end,
                window_start = excluded.window_start
            returning hits, ceil(extract(epoch from window_start + interval '1 minute' - now()))::int
        """), {"b": caller.bucket}).one()
    if hits > caller.limit:
        raise HTTPException(429, f"rate limit: {caller.limit} requests per minute",
                            {"Retry-After": str(max(retry_after, 1))})


def check(request: Request, scope: str) -> Caller:
    caller = authenticate(request)
    authorize(caller, scope)
    return caller


def require(scope: str):
    def dependency(request: Request) -> Caller:
        return check(request, scope)

    return Depends(dependency)
