"""API keys, scopes and rate limits. REST routes, the MCP route and the admin login all check
callers here. A key is stored only as a PBKDF2-HMAC-SHA256 under FOODDB__BACKEND__SECRET_KEY: the token is
shown once, at creation, and a new secret retires every key."""

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from fooddb.db import engine

IMPLIES = {
    "read": {"read"},
    "contribute": {"read", "contribute"},
    "review": {"read", "contribute", "review"},
    "admin": {"read", "contribute", "review", "admin"},
}


@dataclass(frozen=True)
class Caller:
    name: str
    scopes: frozenset[str]
    bucket: str | None  # rate-limit counter; None: not limited here
    limit: int
    key_id: int | None = None
    account_id: int | None = None  # set: a read costs one credit, unless the account is unlimited
    unlimited: bool = False


ANONYMOUS_NAME = "anonymous"


class OutOfCredits(HTTPException):
    def __init__(self):
        super().__init__(402, "out of credits")


def _default_limit() -> int:
    return int(os.environ.get("FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE", "60"))


def _secret() -> bytes | None:
    s = os.environ.get("FOODDB__BACKEND__SECRET_KEY")
    return s.encode() if s else None


def _hash(token: str, secret: bytes) -> str:
    # PBKDF2 keyed by the secret; deterministic, so a presented token is found by its hash. Tokens are
    # 256 random bits, so the iteration count only has to be cheap per request.
    return hashlib.pbkdf2_hmac("sha256", token.encode(), secret, 1000).hex()


def token_hash(token: str) -> str:
    secret = _secret()
    if secret is None:
        raise RuntimeError("set FOODDB__BACKEND__SECRET_KEY")
    return _hash(token, secret)


def _caller(row) -> Caller:
    scopes = frozenset().union(*(IMPLIES[s] for s in row["scopes"]))
    return Caller(row["name"], scopes, f"key:{row['id']}", row["rate_limit"] or _default_limit(), row["id"],
                  row["account_id"], bool(row["unlimited"]))


def create(name: str, scopes: list[str], rate_limit: int | None = None, account_id: int | None = None) -> str:
    if not scopes or not set(scopes) <= IMPLIES.keys():
        raise ValueError(f"scopes must be some of {', '.join(IMPLIES)}")
    secret = _secret()
    if secret is None:
        raise RuntimeError("set FOODDB__BACKEND__SECRET_KEY before creating API keys")
    token = "fdb_" + secrets.token_urlsafe(32)
    with engine().begin() as conn:
        conn.execute(text("insert into api_key (name, token_hash, scopes, rate_limit, account_id) values (:n, :h, :s, :r, :a)"),
                     {"n": name, "h": _hash(token, secret), "s": sorted(set(scopes)), "r": rate_limit, "a": account_id})
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
    """The active key for this token, marked as used now. None without a server secret."""
    secret = _secret()
    if secret is None:
        return None
    with engine().begin() as conn:
        row = conn.execute(text("""
            with k as (update api_key set last_used_at = now() where token_hash = :h and revoked_at is null
                       returning id, name, scopes, rate_limit, account_id)
            select k.*, a.unlimited from k left join account a on a.id = k.account_id
        """), {"h": _hash(token, secret)}).mappings().first()
    return _caller(row) if row else None


def by_id(key_id: int) -> Caller | None:
    with engine().connect() as conn:
        row = conn.execute(text("""select k.id, k.name, k.scopes, k.rate_limit, k.account_id, a.unlimited
                                   from api_key k left join account a on a.id = k.account_id
                                   where k.id = :id and k.revoked_at is null"""), {"id": key_id}).mappings().first()
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
        _count(caller, charge=scope == "read")


def hit(bucket: str, unit: str = "minute") -> tuple[int, int]:
    """Count one hit in a fixed minute or hour window, shared by every API replica: (hits, seconds left)."""
    with engine().begin() as conn:
        return _hit(conn, bucket, unit)


def _hit(conn, bucket: str, unit: str = "minute") -> tuple[int, int]:
    assert unit in ("minute", "hour")
    return conn.execute(text(f"""
        insert into rate_limit (bucket, window_start, hits) values (:b, date_trunc('{unit}', now()), 1)
        on conflict (bucket) do update set
            hits = case when rate_limit.window_start = excluded.window_start then rate_limit.hits + 1 else 1 end,
            window_start = excluded.window_start
        returning hits, ceil(extract(epoch from window_start + interval '1 {unit}' - now()))::int
    """), {"b": bucket}).one()


# One statement: the credit leaves only if one is left, and the month's counter moves with it.
_CHARGE = text("""
    with paid as (update account set credits = credits - 1 where id = :a and credits > 0 returning id)
    insert into usage_month (account_id, month, requests)
    select id, date_trunc('month', now() at time zone 'utc')::date, 1 from paid
    on conflict (account_id, month) do update set requests = usage_month.requests + 1
    returning requests
""")
_USED = text("""
    insert into usage_month (account_id, month, requests)
    values (:a, date_trunc('month', now() at time zone 'utc')::date, 1)
    on conflict (account_id, month) do update set requests = usage_month.requests + 1
    returning requests
""")


def _count(caller: Caller, charge: bool = False) -> None:
    """The rate limit and, for a keyed read of an account, its credit, in one transaction. A refused request
    (429 or 402) costs no credit."""
    paid = True
    with engine().begin() as conn:
        hits, retry_after = _hit(conn, caller.bucket)
        if charge and caller.account_id is not None and hits <= caller.limit:
            paid = conn.execute(_USED if caller.unlimited else _CHARGE, {"a": caller.account_id}).first() is not None
    if hits > caller.limit:
        raise HTTPException(429, f"rate limit: {caller.limit} requests per minute",
                            {"Retry-After": str(max(retry_after, 1))})
    if not paid:
        raise OutOfCredits()


def check(request: Request, scope: str) -> Caller:
    caller = authenticate(request)
    authorize(caller, scope)
    return caller


def counted(request: Request) -> Caller:
    """Open to anyone, with a key or without, but each request counts against the caller's rate limit."""
    caller = authenticate(request)
    if caller.bucket is not None:
        _count(caller)
    return caller


def require(scope: str):
    def dependency(request: Request) -> Caller:
        return check(request, scope)

    return Depends(dependency)
