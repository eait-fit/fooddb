"""Stripe over its REST API with httpx: one Checkout session per pack, and the webhook signature check."""

import hashlib
import hmac
import os
import time

import httpx

PACK_NAME = "fooddb — 100,000 API requests"
PACK_CENTS = 2999
TOLERANCE = 300  # seconds a webhook timestamp may differ from now


class Unavailable(RuntimeError):
    pass


class Refused(ValueError):
    pass


def credits_per_pack() -> int:
    return int(os.environ.get("FOODDB__BACKEND__CREDITS_PER_PACK", "100000"))


def checkout(account_id: int, email: str, base: str) -> str:
    """A Stripe Checkout session for one pack, paid once. Returns the URL Stripe hosts it at."""
    key = os.environ.get("FOODDB__BACKEND__STRIPE_SECRET_KEY")
    if not key:
        raise Unavailable("FOODDB__BACKEND__STRIPE_SECRET_KEY is unset")
    price = os.environ.get("FOODDB__BACKEND__STRIPE_PRICE_ID")
    item = {"line_items[0][quantity]": "1"} | (
        {"line_items[0][price]": price} if price else {
            "line_items[0][price_data][currency]": "eur",
            "line_items[0][price_data][unit_amount]": str(PACK_CENTS),
            "line_items[0][price_data][product_data][name]": PACK_NAME})
    data = {"mode": "payment", "client_reference_id": str(account_id), "customer_email": email, "metadata[app]": "fooddb",
            "success_url": base + "/portal/success?session_id={CHECKOUT_SESSION_ID}", "cancel_url": f"{base}/portal/cancel",
            **item}
    if os.environ.get("FOODDB__BACKEND__STRIPE_AUTOMATIC_TAX", "").lower() in ("1", "true", "yes"):
        data["automatic_tax[enabled]"] = "true"
    r = httpx.post("https://api.stripe.com/v1/checkout/sessions", data=data, headers={"Authorization": f"Bearer {key}"}, timeout=20)
    r.raise_for_status()
    return r.json()["url"]


def verify(payload: bytes, header: str | None, now: float | None = None) -> None:
    """Raise Refused unless header (`t=…,v1=…`) is a Stripe signature of payload under our webhook secret, made now."""
    secret = os.environ.get("FOODDB__BACKEND__STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise Unavailable("FOODDB__BACKEND__STRIPE_WEBHOOK_SECRET is unset")
    parts = [p.partition("=")[::2] for p in (header or "").split(",")]
    try:
        t = int(next(v for k, v in parts if k == "t"))
    except (StopIteration, ValueError):
        raise Refused("no signature timestamp") from None
    good = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(v.encode(), good.encode()) for k, v in parts if k == "v1"):
        raise Refused("bad signature")
    if abs((time.time() if now is None else now) - t) > TOLERANCE:
        raise Refused("stale timestamp")
