"""The developer portal at /portal: magic-link sign-in, keys, credits, Stripe Checkout, and the Stripe webhook.
Server-rendered pages. The session is a signed cookie; every POST form carries a CSRF token."""

import hashlib
import hmac
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.concurrency import run_in_threadpool
from starlette.templating import Jinja2Templates

from fooddb import accounts, auth, billing, mail

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
SESSION, CSRF, FLASH = "fooddb_portal", "fooddb_csrf", "fooddb_flash"
SESSION_SECONDS = 30 * 24 * 3600
LOGINS_PER_IP_HOUR, LOGINS_PER_EMAIL_HOUR = 20, 5
PAID_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}


def _secret() -> str:
    secret = os.environ.get("FOODDB__BACKEND__SECRET_KEY")
    if not secret:
        raise HTTPException(503, "the portal needs FOODDB__BACKEND__SECRET_KEY")
    return secret


router = APIRouter(include_in_schema=False, dependencies=[Depends(_secret)])
webhook = APIRouter(include_in_schema=False)


def _base(request: Request) -> str:
    """Where links we send point. The Host header is the sender's, so it is trusted only for FOODDB__BACKEND__MAIL=log."""
    if url := os.environ.get("FOODDB__BACKEND__PUBLIC_URL"):
        return url.rstrip("/")
    if mail.backend() == "log":
        return str(request.base_url).rstrip("/")
    raise HTTPException(503, "set FOODDB__BACKEND__PUBLIC_URL")


def _mac(value: str) -> str:
    return hmac.new(_secret().encode(), b"csrf:" + value.encode(), hashlib.sha256).hexdigest()


def _cookie(response, request: Request, name: str, value: str, **kw) -> None:
    response.set_cookie(name, value, httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/portal", **kw)


def page(request: Request, name: str, status: int = 200, **context):
    """A page with its CSRF token: a random cookie, and in each form the MAC of it, which only we can make."""
    fresh = None if CSRF in request.cookies else secrets.token_urlsafe(24)
    response = TEMPLATES.TemplateResponse(request, name, {"csrf": _mac(fresh or request.cookies[CSRF]), "error": None} | context,
                                          status_code=status, headers=HEADERS)
    if fresh:
        _cookie(response, request, CSRF, fresh)
    return response


def check_csrf(request: Request, csrf: Annotated[str, Form()] = "") -> None:
    seed = request.cookies.get(CSRF)
    if not seed or not hmac.compare_digest(csrf.encode(), _mac(seed).encode()):
        raise HTTPException(403, "form expired: go back, reload the page and try again")


CSRF_OK = Depends(check_csrf)


def _sessions() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="fooddb-portal-session")


def _flash() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="fooddb-portal-flash")


def current(request: Request) -> dict:
    """The signed-in account, else a redirect to sign in. A session of a deleted account counts as none."""
    try:
        account = accounts.get(_sessions().loads(request.cookies.get(SESSION, ""), max_age=SESSION_SECONDS)["a"])
    except (BadSignature, KeyError, TypeError):
        account = None
    if account is None:
        raise HTTPException(303, headers={"Location": "/portal/login"})
    return account


ACCOUNT = Depends(current)


def _flashed(request: Request) -> str | None:
    """The key the last redirect left in the flash cookie, if it is ours and under a minute old."""
    try:
        return _flash().loads(request.cookies.get(FLASH, ""), max_age=60)
    except BadSignature:
        return None


def _dashboard(request: Request, account: dict, status: int = 200, **context):
    return page(request, "portal.html", status, **{
        "account": account, "keys": accounts.keys(account["id"]), "used": accounts.requests_this_month(account["id"]),
        "purchases": accounts.purchases(account["id"]), "new_key": None,
        "pack": {"price": billing.PACK_CENTS / 100, "credits": billing.credits_per_pack()}} | context)


@router.get("/portal/login")
def login_form(request: Request):
    return page(request, "portal_login.html", sent=False)


@router.post("/portal/login", dependencies=[CSRF_OK])
def login(request: Request, email: Annotated[str, Form()] = ""):
    """Same answer whether or not the address has an account. Limits per IP and per address stop only the mail."""
    ip = request.client.host if request.client else "unknown"
    if auth.hit(f"login-ip:{ip}", "hour")[0] > LOGINS_PER_IP_HOUR:
        return page(request, "portal_login.html", 429, sent=False, error="Too many sign-in requests. Try again later.")
    address = accounts.normalize(email)
    if address is None:
        return page(request, "portal_login.html", 400, sent=False, error="Enter a valid email address.")
    if not mail.configured():
        raise HTTPException(503, "sign-in mail is not configured")
    link = f"{_base(request)}/portal/verify?token="
    if auth.hit("login-email:" + hashlib.sha256(address.encode()).hexdigest(), "hour")[0] <= LOGINS_PER_EMAIL_HOUR:
        try:
            token = accounts.issue_login(accounts.ensure(address))
            mail.send(address, "Sign in to fooddb", f"Open this link to sign in. It works once, for {accounts.LOGIN_MINUTES} minutes.\n\n{link}{token}\n\n"
                      "If you did not ask for it, ignore this mail.")
        except (httpx.HTTPError, RuntimeError):
            log.exception("sign-in mail failed")
    return page(request, "portal_login.html", sent=True)


@router.get("/portal/verify")
def verify_form(request: Request, token: str = ""):
    """The link only shows a button: a mail scanner that opens the link must not use up the token."""
    return page(request, "portal_verify.html", token=token)


@router.post("/portal/verify", dependencies=[CSRF_OK])
def verify(request: Request, token: Annotated[str, Form()] = ""):
    account_id = accounts.redeem_login(token) if token else None
    if account_id is None:
        return page(request, "portal_login.html", 400, sent=False, error="That link is used up or has expired. Ask for a new one.")
    response = RedirectResponse("/portal", 303, headers=HEADERS)
    _cookie(response, request, SESSION, _sessions().dumps({"a": account_id}), max_age=SESSION_SECONDS)
    return response


@router.post("/portal/logout", dependencies=[CSRF_OK])
def logout():
    response = RedirectResponse("/portal/login", 303, headers=HEADERS)
    response.delete_cookie(SESSION, path="/portal")
    return response


@router.get("/portal")
def dashboard(request: Request, account: dict = ACCOUNT):
    new_key = _flashed(request)
    response = _dashboard(request, account, new_key=new_key)
    if FLASH in request.cookies:
        response.delete_cookie(FLASH, path="/portal")
    return response


@router.post("/portal/keys", dependencies=[CSRF_OK])
def new_key(request: Request, account: dict = ACCOUNT):
    token = accounts.create_key(account["id"])
    if token is None:
        return _dashboard(request, account, 409, error=f"At most {accounts.MAX_ACTIVE_KEYS} active keys. Revoke one first.")
    response = RedirectResponse("/portal", 303, headers=HEADERS)
    _cookie(response, request, FLASH, _flash().dumps(token), max_age=60)
    return response


@router.post("/portal/keys/{key_id}/revoke", dependencies=[CSRF_OK])
def revoke_key(key_id: int, account: dict = ACCOUNT):
    if not accounts.revoke_key(account["id"], key_id):
        raise HTTPException(404, "no such active key")
    return RedirectResponse("/portal", 303, headers=HEADERS)


@router.post("/portal/buy", dependencies=[CSRF_OK])
def buy(request: Request, account: dict = ACCOUNT):
    try:
        url = billing.checkout(account["id"], account["email"], _base(request))
    except billing.Unavailable:
        raise HTTPException(503, "buying is not configured") from None
    except (httpx.HTTPError, KeyError) as e:
        log.error("stripe checkout failed: %s", type(e).__name__)
        return _dashboard(request, account, 502, error="The payment provider did not answer. Try again in a minute.")
    return RedirectResponse(url, 303, headers=HEADERS)


@router.get("/portal/success")
def success(request: Request, account: dict = ACCOUNT):
    return page(request, "portal_done.html", paid=True)


@router.get("/portal/cancel")
def cancel(request: Request, account: dict = ACCOUNT):
    return page(request, "portal_done.html", paid=False)


@webhook.post("/v1/stripe/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Stripe's event. Only a correctly signed one counts. A paid pack session of ours adds credits, once."""
    body = await request.body()
    try:
        billing.verify(body, request.headers.get("stripe-signature"))
    except billing.Unavailable:
        raise HTTPException(503, "webhook secret is not set") from None
    except billing.Refused as e:
        raise HTTPException(400, str(e)) from None
    event = json.loads(body)
    session = event.get("data", {}).get("object", {})
    if event.get("type") in PAID_EVENTS and session.get("payment_status") == "paid" and session.get("metadata", {}).get("app") == "fooddb":
        try:
            await run_in_threadpool(accounts.credit_purchase, session)
        except (LookupError, ValueError, KeyError):
            log.error("paid session %s names no account of ours", session.get("id"))
            raise HTTPException(500, "paid session without a known account") from None
    return {"received": True}
