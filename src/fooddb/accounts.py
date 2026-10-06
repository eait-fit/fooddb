"""Developer accounts: sign-in tokens, the keys an account owns, prepaid credits and Stripe purchases."""

import secrets

from sqlalchemy import text

from fooddb import auth, billing
from fooddb.db import engine

LOGIN_MINUTES = 15
MAX_ACTIVE_KEYS = 10


def normalize(email: str) -> str | None:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    ok = (len(email) <= 254 and local and "@" not in domain and "." in domain.strip(".") and domain == domain.strip(".")
          and not any(c.isspace() for c in email))
    return email if ok else None


def ensure(email: str) -> int:
    with engine().begin() as conn:
        return conn.execute(text("insert into account (email) values (:e) on conflict (email) do update set email = excluded.email "
                                 "returning id"), {"e": email}).scalar_one()


def get(account_id: int) -> dict | None:
    with engine().connect() as conn:
        row = conn.execute(text("select id, email, credits, unlimited from account where id = :a"), {"a": account_id}).mappings().first()
    return dict(row) if row else None


def issue_login(account_id: int) -> str:
    """A single-use sign-in token. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    with engine().begin() as conn:
        conn.execute(text("insert into login_token (token_hash, account_id, expires_at) "
                          "values (:h, :a, now() + make_interval(mins => :m))"),
                     {"h": auth.token_hash(token), "a": account_id, "m": LOGIN_MINUTES})
    return token


def redeem_login(token: str) -> int | None:
    """The account this token signs in, once: the same token is dead after, and after its 15 minutes."""
    with engine().begin() as conn:
        return conn.execute(text("update login_token set used_at = now() where token_hash = :h and used_at is null "
                                 "and expires_at > now() returning account_id"), {"h": auth.token_hash(token)}).scalar()


def create_key(account_id: int) -> str | None:
    """A read key for the account, named at random: key names are unique among active keys. None at the key limit."""
    with engine().connect() as conn:
        active = conn.execute(text("select count(*) from api_key where account_id = :a and revoked_at is null"), {"a": account_id}).scalar_one()
    if active >= MAX_ACTIVE_KEYS:
        return None
    return auth.create(f"account-{account_id}-{secrets.token_hex(3)}", ["read"], account_id=account_id)


def revoke_key(account_id: int, key_id: int) -> bool:
    with engine().begin() as conn:
        return conn.execute(text("update api_key set revoked_at = now() where id = :k and account_id = :a and revoked_at is null"),
                            {"k": key_id, "a": account_id}).rowcount > 0


def keys(account_id: int) -> list[dict]:
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "select id, name, created_at, last_used_at from api_key where account_id = :a and revoked_at is null order by id"),
            {"a": account_id}).mappings()]


def requests_this_month(account_id: int) -> int:
    with engine().connect() as conn:
        return conn.execute(text("select coalesce(sum(requests), 0) from usage_month "
                                 "where account_id = :a and month = date_trunc('month', now() at time zone 'utc')::date"),
                            {"a": account_id}).scalar_one()


def purchases(account_id: int) -> list[dict]:
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "select created_at, amount_cents, currency, credits from purchase where account_id = :a order by id desc"),
            {"a": account_id}).mappings()]


def credit_purchase(session: dict) -> bool:
    """Record a paid Checkout session and add the pack's credits in one transaction. False: already recorded.
    LookupError: the session names no account."""
    sid, account_id = session["id"], int(session["client_reference_id"])
    with engine().begin() as conn:
        added = conn.execute(text("""
            insert into purchase (account_id, stripe_session_id, amount_cents, currency, credits)
            select id, :s, :amount, :cur, :n from account where id = :a
            on conflict (stripe_session_id) do nothing returning id
        """), {"s": sid, "a": account_id, "amount": session.get("amount_total") or 0,
               "cur": (session.get("currency") or "").lower(), "n": billing.credits_per_pack()}).first()
        if added is None:
            if conn.execute(text("select 1 from purchase where stripe_session_id = :s"), {"s": sid}).first():
                return False
            raise LookupError(f"account {account_id} not found")
        conn.execute(text("update account set credits = credits + :n, stripe_customer_id = coalesce(:c, stripe_customer_id) where id = :a"),
                     {"n": billing.credits_per_pack(), "c": session.get("customer"), "a": account_id})
    return True


def listing() -> list[dict]:
    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text("select id, email, credits, unlimited, created_at from account order by id")).mappings()]


def grant(email: str, credits: int) -> int:
    """Add credits to the account of this email, which is created when absent. Returns the new balance."""
    with engine().begin() as conn:
        return conn.execute(text("insert into account (email, credits) values (:e, :n) on conflict (email) do update set "
                                 "credits = account.credits + :n returning credits"), {"e": email, "n": credits}).scalar_one()


def set_unlimited(email: str, on: bool) -> None:
    with engine().begin() as conn:
        conn.execute(text("insert into account (email, unlimited) values (:e, :u) on conflict (email) do update set unlimited = :u"),
                     {"e": email, "u": on})
