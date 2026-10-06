"""Developer portal: magic-link accounts, self-serve keys, prepaid credits, Stripe webhook. Database suite.
Stripe and the mail sender are fakes; the webhook signatures are real HMACs under a fake secret."""

import hashlib
import hmac
import json
import logging
import re
import threading
import time

import httpx
import pytest

from tests.test_db import clean, client, ingest_typo, key, pytestmark, rec  # noqa: F401

PUBLIC = "https://api.test"
WHSEC = "test-webhook-secret"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("FOODDB__BACKEND__PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_WEBHOOK_SECRET", WHSEC)
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_SECRET_KEY", "fake-stripe-key")
    monkeypatch.setenv("FOODDB__BACKEND__REQUIRE_KEY_FOR_READS", "true")
    for k in ("STRIPE_PRICE_ID", "STRIPE_AUTOMATIC_TAX", "STRIPE_TAX_BEHAVIOR", "STRIPE_TAX_CODE", "CREDITS_PER_PACK", "MAIL", "RESEND_API_KEY"):
        monkeypatch.delenv(f"FOODDB__BACKEND__{k}", raising=False)


@pytest.fixture
def outbox(monkeypatch):
    from fooddb import mail

    sent: list[tuple[str, str]] = []
    monkeypatch.setenv("FOODDB__BACKEND__MAIL", "log")
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.append((to, body)))
    return sent


def web(https: bool = True):
    from fastapi.testclient import TestClient

    from fooddb.api import app

    return TestClient(app, base_url="https://testserver" if https else "http://testserver")


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def request_link(c, email: str, outbox) -> str:
    form = c.get("/portal/login")
    assert form.status_code == 200
    r = c.post("/portal/login", data={"email": email, "csrf": csrf_of(form.text)})
    assert r.status_code == 200, r.text
    return re.search(r"/portal/verify\?token=[\w-]+", outbox[-1][1]).group()


def sign_in(c, email: str, outbox):
    link = request_link(c, email, outbox)
    page = c.get(link)
    token = link.split("token=")[1]
    r = c.post("/portal/verify", data={"token": token, "csrf": csrf_of(page.text)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/portal", r.text
    return c


def dash(c) -> str:
    r = c.get("/portal")
    assert r.status_code == 200, r.status_code
    return r.text


def post(c, path: str, **data):
    return c.post(path, data={"csrf": csrf_of(dash(c)), **data}, follow_redirects=False)


def db(sql: str, **params):
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().begin() as conn:
        r = conn.execute(text(sql), params)
        return list(r.mappings()) if r.returns_rows else r.rowcount


def account(email: str) -> dict:
    return db("select * from account where email = :e", e=email)[0]


def portal_key(c) -> str:
    return re.search(r"fdb_[\w-]+", post(c, "/portal/keys").text.replace("&#45;", "-")).group()


def signed(body: bytes, secret: str = WHSEC, ts: int | None = None) -> dict:
    t = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def paid_event(session_id="cs_1", account_id=1, status="paid", kind="checkout.session.completed") -> bytes:
    return json.dumps({"id": "evt_1", "type": kind, "data": {"object": {
        "id": session_id, "client_reference_id": str(account_id), "payment_status": status, "metadata": {"app": "fooddb"},
        "amount_total": 2999, "currency": "eur", "customer": "cus_1"}}}).encode()


def webhook(body: bytes, headers: dict | None = None):
    return client().post("/v1/stripe/webhook", content=body, headers=signed(body) if headers is None else headers)


def test_signup_magic_link_session_and_logout(outbox):
    c = web()
    sign_in(c, "New@Example.com", outbox)
    assert outbox[0][0] == "new@example.com"
    assert account("new@example.com")["credits"] == 0
    assert "new@example.com" in dash(c)
    r = post(c, "/portal/logout")
    assert r.status_code == 303
    assert c.get("/portal", follow_redirects=False).headers["location"] == "/portal/login"


def test_session_cookie_is_secure_over_https_only_and_lasts_30_days(outbox):
    for https in (True, False):
        c = web(https)
        link = request_link(c, f"u{https}@example.com", outbox)
        page = c.get(link)
        r = c.post("/portal/verify", data={"token": link.split("token=")[1], "csrf": csrf_of(page.text)},
                   follow_redirects=False)
        [session] = [h for h in r.headers.get_list("set-cookie") if h.startswith("fooddb_portal=")]
        assert "HttpOnly" in session and "samesite=lax" in session.lower() and "Max-Age=2592000" in session
        assert ("Secure" in session) is https


def test_the_link_points_at_the_configured_host_not_the_host_header(outbox):
    c = web()
    form = c.get("/portal/login")
    c.post("/portal/login", data={"email": "a@example.com", "csrf": csrf_of(form.text)}, headers={"Host": "evil.test"})
    assert PUBLIC in outbox[0][1] and "evil.test" not in outbox[0][1]


def test_a_link_works_once_and_expires(outbox):
    c = web()
    link = request_link(c, "once@example.com", outbox)
    token = link.split("token=")[1]
    page = c.get(link)
    assert db("select count(*) n from login_token where used_at is null")[0]["n"] == 1  # a GET (a mail scanner) burns nothing
    assert c.post("/portal/verify", data={"token": token, "csrf": csrf_of(page.text)}, follow_redirects=False).status_code == 303
    again = web()
    page = again.get(link)
    assert again.post("/portal/verify", data={"token": token, "csrf": csrf_of(page.text)}, follow_redirects=False).status_code == 400

    stale = web()
    link = request_link(stale, "late@example.com", outbox)
    db("update login_token set expires_at = now() - interval '1 second'")
    page = stale.get(link)
    r = stale.post("/portal/verify", data={"token": link.split("token=")[1], "csrf": csrf_of(page.text)}, follow_redirects=False)
    assert r.status_code == 400
    assert stale.get("/portal", follow_redirects=False).status_code == 303


def test_a_link_expires_after_15_minutes_and_is_stored_hashed(outbox):
    request_link(web(), "h@example.com", outbox)
    row = db("select token_hash, extract(epoch from expires_at - now()) left from login_token")[0]
    assert 14 * 60 < row["left"] <= 15 * 60
    token = outbox[0][1].split("token=")[1].split()[0]
    assert token not in str(row) and len(row["token_hash"]) == 64


def test_login_does_not_reveal_whether_an_account_exists(outbox):
    c = web()
    request_link(c, "known@example.com", outbox)
    bodies = []
    for email in ("known@example.com", "stranger@example.com"):
        form = c.get("/portal/login")
        r = c.post("/portal/login", data={"email": email, "csrf": csrf_of(form.text)})
        bodies.append((r.status_code, re.sub(r"\s+", " ", re.sub(r'value="[^"]*"', "", r.text))))
    assert bodies[0] == bodies[1]


def test_login_requests_are_limited_per_email_and_per_ip(outbox):
    c = web()
    for _ in range(8):
        form = c.get("/portal/login")
        r = c.post("/portal/login", data={"email": "spam@example.com", "csrf": csrf_of(form.text)})
        assert r.status_code == 200  # over the limit the answer is the same; only the mail stops
    assert len(outbox) == 5
    codes = []
    for i in range(30):
        form = c.get("/portal/login")
        codes.append(c.post("/portal/login", data={"email": f"p{i}@example.com", "csrf": csrf_of(form.text)}).status_code)
    assert codes[-1] == 429 and codes[0] == 200


def test_every_portal_post_needs_the_csrf_token(outbox):
    c = web()
    c.get("/portal/login")
    assert c.post("/portal/login", data={"email": "x@example.com"}).status_code == 403
    assert c.post("/portal/login", data={"email": "x@example.com", "csrf": "forged"}).status_code == 403
    assert c.post("/portal/verify", data={"token": "t"}).status_code == 403
    assert outbox == []
    sign_in(c, "x@example.com", outbox)
    k = portal_key(c)
    kid = db("select id from api_key")[0]["id"]
    for path in ("/portal/keys", f"/portal/keys/{kid}/revoke", "/portal/buy", "/portal/logout"):
        assert c.post(path, data={"csrf": "forged"}, follow_redirects=False).status_code == 403, path
        assert c.post(path, follow_redirects=False).status_code == 403, path
    db("update account set credits = 1")
    assert client(k).get("/v1/snapshots").status_code == 200  # nothing above revoked it
    other = web()
    other.get("/portal/login")
    assert c.post("/portal/keys", data={"csrf": csrf_of(other.get("/portal/login").text)}).status_code == 403  # another browser's token


def test_keys_are_created_shown_once_and_revoked_only_by_their_owner(outbox):
    a, b = web(), web()
    sign_in(a, "a@example.com", outbox)
    sign_in(b, "b@example.com", outbox)
    token = portal_key(a)
    db("update account set credits = 10")
    assert token not in dash(a) and token not in dash(b)
    [row] = db("select id, scopes, account_id, name from api_key")
    assert row["scopes"] == ["read"] and row["account_id"] == account("a@example.com")["id"]
    assert token not in str(row)
    assert post(b, f"/portal/keys/{row['id']}/revoke").status_code == 404
    assert client(token).get("/v1/snapshots").status_code == 200
    assert post(a, f"/portal/keys/{row['id']}/revoke").status_code == 303
    assert client(token).get("/v1/snapshots").status_code == 401


def test_a_portal_key_cannot_be_given_another_scope(outbox):
    c = web()
    sign_in(c, "s@example.com", outbox)
    post(c, "/portal/keys", scope="admin", scopes="admin")
    assert db("select scopes from api_key")[0]["scopes"] == ["read"]


def test_a_read_costs_one_credit_and_zero_credits_answers_402(outbox):
    ingest_typo()
    c = web()
    sign_in(c, "pay@example.com", outbox)
    k = portal_key(c)
    assert client(k).get("/v1/snapshots").status_code == 402
    r = client(k).get("/v1/snapshots")
    assert r.json()["detail"] == "out of credits" and r.json()["buy"] == f"{PUBLIC}/portal/buy"
    db("update account set credits = 2")
    assert [client(k).get("/v1/snapshots").status_code for _ in range(3)] == [200, 200, 402]
    assert account("pay@example.com")["credits"] == 0


def test_mcp_over_http_is_refused_at_zero_credits_too(outbox):
    c = web()
    sign_in(c, "mcp@example.com", outbox)
    k = portal_key(c)
    r = client(k).post("/mcp", json={})
    assert r.status_code == 402 and r.json() == {"detail": "out of credits", "buy": f"{PUBLIC}/portal/buy"}


def test_credits_are_shared_by_all_keys_of_an_account(outbox):
    c = web()
    sign_in(c, "two@example.com", outbox)
    k1, k2 = portal_key(c), portal_key(c)
    db("update account set credits = 2")
    assert client(k1).get("/v1/snapshots").status_code == 200
    assert client(k2).get("/v1/snapshots").status_code == 200
    assert client(k1).get("/v1/snapshots").status_code == 402


def test_a_rate_limited_request_costs_no_credit(outbox):
    c = web()
    sign_in(c, "fast@example.com", outbox)
    from fooddb import auth

    k = auth.create("fast", ["read"], rate_limit=1, account_id=account("fast@example.com")["id"])
    db("update account set credits = 10")
    assert [client(k).get("/v1/snapshots").status_code for _ in range(3)] == [200, 429, 429]
    assert account("fast@example.com")["credits"] == 9


def test_ownerless_rapidapi_unlimited_and_write_calls_are_not_charged(monkeypatch, outbox):
    from fooddb import auth

    monkeypatch.setenv("FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET", "s3cret")
    ingest_typo()
    assert client(key("read", name="eait")).get("/v1/snapshots").status_code == 200  # ownerless: never charged
    assert client().get("/v1/snapshots", headers={"X-RapidAPI-Proxy-Secret": "s3cret"}).status_code == 200
    c = web()
    sign_in(c, "u@example.com", outbox)
    acct = account("u@example.com")
    db("update account set unlimited = true")
    k = portal_key(c)
    assert [client(k).get("/v1/snapshots").status_code for _ in range(3)] == [200] * 3
    assert account("u@example.com")["credits"] == 0
    assert re.search(r"Requests this month</dt>\s*<dd>3<", dash(c))
    db("update account set unlimited = false, credits = 5")
    rk = auth.create("rev", ["review"], account_id=acct["id"])
    assert client(rk).get("/v1/review").status_code == 200
    assert account("u@example.com")["credits"] == 5


def test_concurrent_reads_never_take_credits_below_zero(outbox):
    c = web()
    sign_in(c, "race@example.com", outbox)
    from fooddb import auth

    k = auth.create("race", ["read"], rate_limit=1000, account_id=account("race@example.com")["id"])
    db("update account set credits = 5")
    results, lock = [], threading.Lock()

    def hit():
        code = client(k).get("/v1/snapshots").status_code
        with lock:
            results.append(code)

    threads = [threading.Thread(target=hit) for _ in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200] * 5 + [402] * 20
    assert account("race@example.com")["credits"] == 0


def test_monthly_usage_counts_each_charged_read_and_shows_on_the_dashboard(outbox):
    c = web()
    sign_in(c, "use@example.com", outbox)
    k = portal_key(c)
    db("update account set credits = 10")
    for _ in range(4):
        client(k).get("/v1/snapshots")
    [row] = db("select requests, month = date_trunc('month', now() at time zone 'utc')::date this_month from usage_month")
    assert row["requests"] == 4 and row["this_month"]
    page = dash(c)
    assert "Requests this month" in page and re.search(r"Requests this month</dt>\s*<dd>4<", page)
    assert re.search(r"Credits left</dt>\s*<dd>6<", page)


def test_buy_creates_a_checkout_session_for_the_account(monkeypatch, outbox):
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return httpx.Response(200, json={"id": "cs_new", "url": "https://checkout.stripe.test/c/cs_new"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr("fooddb.billing.httpx.post", fake_post)
    c = web()
    sign_in(c, "buyer@example.com", outbox)
    r = post(c, "/portal/buy")
    assert r.status_code == 303 and r.headers["location"] == "https://checkout.stripe.test/c/cs_new"
    [(url, kw)] = calls
    assert url == "https://api.stripe.com/v1/checkout/sessions"
    assert kw["headers"]["Authorization"] == "Bearer fake-stripe-key"
    d = kw["data"]
    assert d["metadata[app]"] == "fooddb"
    assert d["mode"] == "payment" and d["client_reference_id"] == str(account("buyer@example.com")["id"])
    assert d["customer_email"] == "buyer@example.com" and d["line_items[0][quantity]"] == "1"
    assert d["line_items[0][price_data][currency]"] == "eur" and d["line_items[0][price_data][unit_amount]"] == "2999"
    assert d["line_items[0][price_data][product_data][name]"] == "fooddb — 100,000 API requests"
    assert d["success_url"].startswith(f"{PUBLIC}/portal/success") and d["cancel_url"] == f"{PUBLIC}/portal/cancel"
    assert "automatic_tax[enabled]" not in d and "billing_address_collection" not in d and "line_items[0][price]" not in d
    assert d["line_items[0][price_data][tax_behavior]"] == "inclusive"
    assert d["line_items[0][price_data][product_data][tax_code]"] == "txcd_10000000"


def test_checkout_uses_the_configured_price_and_stripe_tax(monkeypatch, outbox):
    calls = []
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_PRICE_ID", "price_fake")
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_AUTOMATIC_TAX", "true")
    monkeypatch.setattr("fooddb.billing.httpx.post", lambda url, **kw: calls.append(kw) or httpx.Response(
        200, json={"url": "https://checkout.stripe.test/x"}, request=httpx.Request("POST", url)))
    c = web()
    sign_in(c, "tax@example.com", outbox)
    assert post(c, "/portal/buy").status_code == 303
    d = calls[0]["data"]
    assert d["line_items[0][price]"] == "price_fake" and d["automatic_tax[enabled]"] == "true"
    assert d["billing_address_collection"] == "required" and "customer_update[address]" not in d
    assert not any("price_data" in k for k in d)


def test_checkout_tax_behavior_and_code_are_configurable_and_validated(monkeypatch, outbox):
    calls = []
    monkeypatch.setattr("fooddb.billing.httpx.post", lambda url, **kw: calls.append(kw) or httpx.Response(
        200, json={"url": "https://checkout.stripe.test/x"}, request=httpx.Request("POST", url)))
    c = web()
    sign_in(c, "cfg@example.com", outbox)
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_TAX_BEHAVIOR", "Exclusive")
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_TAX_CODE", "txcd_99999999")
    assert post(c, "/portal/buy").status_code == 303
    d = calls[0]["data"]
    assert d["line_items[0][price_data][tax_behavior]"] == "exclusive"
    assert d["line_items[0][price_data][product_data][tax_code]"] == "txcd_99999999"
    monkeypatch.setenv("FOODDB__BACKEND__STRIPE_TAX_BEHAVIOR", "unspecified")
    assert post(c, "/portal/buy").status_code == 503 and len(calls) == 1


def test_buy_without_a_stripe_key_is_refused_and_a_stripe_error_leaks_nothing(monkeypatch, outbox):
    c = web()
    sign_in(c, "err@example.com", outbox)
    monkeypatch.setattr("fooddb.billing.httpx.post", lambda url, **kw: httpx.Response(
        402, json={"error": {"message": "secret detail"}}, request=httpx.Request("POST", url)))
    r = post(c, "/portal/buy")
    assert r.status_code == 502 and "secret detail" not in r.text and "fake-stripe-key" not in r.text
    monkeypatch.delenv("FOODDB__BACKEND__STRIPE_SECRET_KEY")
    assert post(c, "/portal/buy").status_code == 503


def test_webhook_refuses_a_bad_or_missing_signature_or_secret(outbox):
    sign_in(web(), "w@example.com", outbox)
    body = paid_event()
    assert client().post("/v1/stripe/webhook", content=body).status_code == 400
    assert webhook(body, signed(body, "wrong-secret")).status_code == 400
    assert webhook(body, signed(body, ts=int(time.time()) - 3600)).status_code == 400  # replayed
    tampered = signed(body)
    assert webhook(body.replace(b"2999", b"9999"), tampered).status_code == 400
    assert webhook(body, {"Stripe-Signature": "garbage"}).status_code == 400
    assert account("w@example.com")["credits"] == 0 and db("select count(*) n from purchase")[0]["n"] == 0
    import os

    os.environ.pop("FOODDB__BACKEND__STRIPE_WEBHOOK_SECRET")
    assert webhook(body, signed(body, "")).status_code == 503


def test_a_paid_session_credits_the_account_once_even_if_delivered_twice(outbox):
    sign_in(web(), "paid@example.com", outbox)
    aid = account("paid@example.com")["id"]
    body = paid_event("cs_paid", aid)
    assert webhook(body).status_code == 200 and webhook(body).status_code == 200
    assert account("paid@example.com")["credits"] == 100000
    [p] = db("select * from purchase")
    assert (p["stripe_session_id"], p["amount_cents"], p["currency"], p["credits"], p["account_id"]) == ("cs_paid", 2999, "eur", 100000, aid)
    assert account("paid@example.com")["stripe_customer_id"] == "cus_1"
    assert webhook(paid_event("cs_two", aid)).status_code == 200
    assert account("paid@example.com")["credits"] == 200000


def test_pack_size_is_configurable(monkeypatch, outbox):
    monkeypatch.setenv("FOODDB__BACKEND__CREDITS_PER_PACK", "500")
    sign_in(web(), "pack@example.com", outbox)
    webhook(paid_event("cs_x", account("pack@example.com")["id"]))
    assert account("pack@example.com")["credits"] == 500


def test_an_unpaid_session_and_other_events_are_ignored(outbox):
    sign_in(web(), "ign@example.com", outbox)
    aid = account("ign@example.com")["id"]
    assert webhook(paid_event("cs_u", aid, status="unpaid")).status_code == 200
    assert webhook(paid_event("cs_o", aid, kind="invoice.paid")).status_code == 200
    assert account("ign@example.com")["credits"] == 0 and db("select count(*) n from purchase")[0]["n"] == 0
    assert webhook(paid_event("cs_late", aid, kind="checkout.session.async_payment_succeeded")).status_code == 200
    assert account("ign@example.com")["credits"] == 100000


def test_a_paid_session_that_is_not_ours_is_ignored(outbox):
    sign_in(web(), "own@example.com", outbox)
    foreign = json.loads(paid_event("cs_f", account("own@example.com")["id"]))
    del foreign["data"]["object"]["metadata"]
    assert webhook(json.dumps(foreign).encode()).status_code == 200
    assert account("own@example.com")["credits"] == 0


def test_a_paid_session_for_an_unknown_account_is_not_swallowed():
    assert webhook(paid_event("cs_none", 424242)).status_code == 500
    assert db("select count(*) n from purchase")[0]["n"] == 0


def test_purchase_history_and_credits_show_on_the_dashboard(outbox):
    c = web()
    sign_in(c, "hist@example.com", outbox)
    webhook(paid_event("cs_h", account("hist@example.com")["id"]))
    page = dash(c)
    assert "29.99" in page and "100000" in page.replace(",", "").replace("&#8239;", "")
    assert web().get("/portal/success").status_code in (200, 303)
    assert web().get("/portal/cancel").status_code in (200, 303)


def test_portal_pages_need_a_session():
    c = web()
    for path in ("/portal", "/portal/success"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/portal/login", path
    for path in ("/portal/keys", "/portal/buy", "/portal/logout"):
        assert c.post(path, data={"csrf": "x"}, follow_redirects=False).status_code in (303, 403, 401), path
    assert c.get("/portal", headers={"Cookie": "fooddb_portal=forged"}, follow_redirects=False).status_code == 303


def test_a_session_of_a_deleted_account_is_refused(outbox):
    c = web()
    sign_in(c, "gone@example.com", outbox)
    db("delete from api_key")
    db("delete from login_token")
    db("delete from usage_month")
    db("delete from account")
    assert c.get("/portal", follow_redirects=False).status_code == 303


def test_log_mail_backend_writes_the_link_only_when_asked_for_explicitly(monkeypatch, caplog):
    from fooddb import mail

    caplog.set_level(logging.INFO)
    with pytest.raises(RuntimeError):
        mail.send("a@example.com", "s", "body with link")
    assert "body with link" not in caplog.text
    monkeypatch.setenv("FOODDB__BACKEND__MAIL", "log")
    mail.send("a@example.com", "s", "body with link")
    assert "body with link" in caplog.text


def test_resend_backend_posts_to_the_resend_api(monkeypatch):
    from fooddb import mail

    calls = []
    monkeypatch.setenv("FOODDB__BACKEND__RESEND_API_KEY", "fake-resend-key")
    monkeypatch.setenv("FOODDB__BACKEND__MAIL_FROM", "fooddb <login@mail.test>")
    monkeypatch.setattr("fooddb.mail.httpx.post", lambda url, **kw: calls.append((url, kw)) or httpx.Response(
        200, json={"id": "1"}, request=httpx.Request("POST", url)))
    mail.send("to@example.com", "Sign in", "the body")
    [(url, kw)] = calls
    assert url == "https://api.resend.com/emails" and kw["headers"]["Authorization"] == "Bearer fake-resend-key"
    assert kw["json"] == {"from": "fooddb <login@mail.test>", "to": ["to@example.com"], "subject": "Sign in", "text": "the body"}


def test_a_mail_failure_gives_the_same_page_and_logs_no_link(monkeypatch, caplog):
    from fooddb import mail

    def broken(to, subject, body):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(mail, "send", broken)
    monkeypatch.setenv("FOODDB__BACKEND__MAIL", "log")
    caplog.set_level(logging.INFO)
    c = web()
    r = c.post("/portal/login", data={"email": "m@example.com", "csrf": csrf_of(c.get("/portal/login").text)})
    assert r.status_code == 200 and "/portal/verify" not in caplog.text


def test_cli_accounts_list_grant_and_set_unlimited():
    from typer.testing import CliRunner

    from fooddb.cli import app

    run = CliRunner().invoke
    assert run(app, ["accounts", "grant", "Cli@Example.com", "250"]).exit_code == 0
    assert run(app, ["accounts", "grant", "cli@example.com", "50"]).exit_code == 0
    assert account("cli@example.com")["credits"] == 300
    assert run(app, ["accounts", "set-unlimited", "cli@example.com"]).exit_code == 0
    assert account("cli@example.com")["unlimited"]
    listed = run(app, ["accounts", "list"]).output
    assert "cli@example.com" in listed and "300" in listed and "unlimited" in listed
    assert run(app, ["accounts", "set-unlimited", "cli@example.com", "--off"]).exit_code == 0
    assert not account("cli@example.com")["unlimited"]
    assert run(app, ["accounts", "grant", "cli@example.com", "0"]).exit_code != 0


def test_admin_shows_accounts_and_purchases_read_only(outbox):
    sign_in(web(), "adm@example.com", outbox)
    webhook(paid_event("cs_a", account("adm@example.com")["id"]))
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="ops")},
                  follow_redirects=False).status_code == 302
    assert "adm@example.com" in c.get("/admin/account/list").text
    assert "cs_a" in c.get("/admin/purchase/list").text
    for view in ("account", "purchase"):
        assert c.get(f"/admin/{view}/create").status_code in (403, 404)
