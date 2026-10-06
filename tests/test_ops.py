"""The request log and the admin panel pages and actions: Overview, Jobs, Requests, Users. Database suite."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_db import clean, client, ingest_typo, key, pytestmark, rec  # noqa: F401

PAGES = ("overview", "jobs", "requests", "users")


def rows(sql: str = "select * from request_log order by id", **params) -> list[dict]:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def admin(name: str = "ops"):
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name=name)},
                  follow_redirects=False).status_code == 302
    return c


def csrf(c, page: str = "users") -> str:
    return re.search(r'name="csrf" value="([^"]+)"', c.get(f"/admin/{page}").text).group(1)


def account(email: str = "dev@example.com", credits: int = 0) -> int:
    from fooddb import accounts

    accounts.grant(email, credits) if credits else None
    return accounts.ensure(email)


def account_row(account_id: int) -> dict:
    return rows("select * from account where id = :a", a=account_id)[0]


def key_row(name: str) -> dict:
    return rows("select * from api_key where name = :n", n=name)[0]


# --- the request log -------------------------------------------------------------------------------------------

def test_a_request_logs_one_row_with_its_route_template_and_nothing_of_the_url():
    from fooddb import ingest

    ingest.run("t", "r1", [rec(id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0",
                               gtin14="04006381333931", name="Hummus")])
    token = key("read", name="reader")
    r = client(token).get("/v1/products/4006381333931", params={"include": "off", "snapshot": "2026-01-01"})
    assert r.status_code in (200, 404)
    [row] = rows()
    assert (row["method"], row["route"], row["status"]) == ("GET", "/v1/products/{barcode}", r.status_code)
    assert (row["key_name"], row["account_id"]) == ("reader", None) and row["key_id"] == key_row("reader")["id"]
    assert row["latency_ms"] >= 0 and row["bytes"] == len(r.content)
    assert re.fullmatch(r"[0-9a-f]{8}", row["ip_hash"])
    assert "testclient" not in str(row) and "127.0.0.1" not in str(row)
    flat = " ".join(str(v) for k, v in row.items() if k != "at")
    assert "4006381333931" not in flat and "include" not in flat and "2026" not in flat and token not in flat


def test_search_terms_stay_out_of_the_log():
    client().get("/v1/foods", params={"q": "secret hummus"})
    assert [r["route"] for r in rows()] == ["/v1/foods"]
    assert "hummus" not in str(rows())


def test_an_unmatched_path_logs_a_placeholder_not_the_path():
    assert client().get("/v1/never-heard-of/4006381333931").status_code == 404
    [row] = rows()
    assert row["route"] == "(unmatched)" and row["status"] == 404 and "4006381333931" not in str(row)


def test_a_refused_key_logs_its_status_and_no_identity():
    assert client("fdb_not-a-key").get("/v1/foods", params={"q": "hummus"}).status_code == 401
    [row] = rows()
    assert (row["status"], row["key_id"], row["key_name"]) == (401, None, None)
    assert "fdb_not-a-key" not in str(row)


def test_an_account_request_logs_its_account_and_a_402():
    from fooddb import auth

    a = account()
    token = auth.create("acct-key", ["read"], account_id=a)
    assert client(token).get("/v1/foods", params={"q": "hummus"}).status_code == 402
    [row] = rows()
    assert (row["status"], row["account_id"], row["key_name"]) == (402, a, "acct-key")


def test_health_probes_and_the_admin_are_not_logged():
    client().get("/livez")
    client().get("/healthz")
    admin().get("/admin/overview")
    assert rows() == []
    client().get("/v1/snapshots")
    assert len(rows()) == 1


def test_the_prune_job_deletes_rows_past_the_retention(monkeypatch):
    from sqlalchemy import text

    from fooddb import jobs
    from fooddb.db import engine

    with engine().begin() as conn:
        for days in (40, 31, 29, 1):
            conn.execute(text("insert into request_log (at, method, route, status, latency_ms) values (:at, 'GET', '/x', 200, 1)"),
                         {"at": datetime.now(UTC) - timedelta(days=days)})
    jobs.prune_request_log()
    assert len(rows()) == 2
    monkeypatch.setenv("FOODDB__BACKEND__REQUEST_LOG_DAYS", "7")
    jobs.prune_request_log()
    assert len(rows()) == 1


def test_the_worker_schedules_the_prune_daily():
    from sqlalchemy import text

    from fooddb import jobs
    from fooddb.db import engine

    jobs.queue().schedule(jobs.prune_request_log, cron=jobs.PRUNE_CRON)
    with engine().connect() as conn:
        assert conn.execute(text("select cron from pq_periodic where name like '%prune_request_log'")).scalar() == jobs.PRUNE_CRON
    jobs.queue().unschedule(jobs.prune_request_log)


# --- pages -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("page", PAGES)
def test_each_page_needs_the_admin_login(page):
    r = client().get(f"/admin/{page}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/admin/login")
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("review")}).status_code == 400
    assert c.get(f"/admin/{page}", follow_redirects=False).status_code == 302
    assert admin().get(f"/admin/{page}").status_code == 200


def seed():
    from sqlalchemy import text

    from fooddb import auth, health, ingest, snapshot
    from fooddb.db import engine

    ingest.run("fdc-foundation", "r1", [rec(), rec(id="off:1", source="off", layer="off", licence="ODbL-1.0", name="Off thing")])
    ingest_typo()
    health.checked("ciqual")
    snapshot.build()
    a = account("dev@example.com", 500)
    auth.create("dev-live", ["read"], account_id=a)
    auth.create("dev-old", ["read"], account_id=a)
    auth.revoke("dev-old")
    with engine().begin() as conn:
        conn.execute(text("insert into purchase (account_id, stripe_session_id, amount_cents, currency, credits) "
                          "values (:a, 'cs_1', 2999, 'eur', 100000)"), {"a": a})
        conn.execute(text("insert into usage_month values (:a, date_trunc('month', now() at time zone 'utc')::date, 42)"), {"a": a})
        conn.execute(text("insert into fetch_run (fetcher, ref, status, foods, observations, error, finished_at) values "
                          "('ciqual', '2026', 'failed', 0, 0, 'boom: bad zip', now())"))
        conn.execute(text("insert into pq_tasks (name, payload, priority, status, run_at, error, attempts, started_at, completed_at) "
                          "values ('fooddb.jobs:fetch_table', '{\"args\": [], \"kwargs\": {\"source\": \"ciqual\"}}', 0, 'FAILED', now(), "
                          "'Traceback: ciqual exploded', 1, now() - interval '5 seconds', now())"))
    return a


def test_the_pages_show_what_the_issue_lists():
    seed()
    for _ in range(3):
        client(key("read", name=f"r{_}")).get("/v1/foods", params={"q": "hummus"})
    client("fdb_nope").get("/v1/foods", params={"q": "hummus"})
    c = admin()
    overview = c.get("/admin/overview").text
    for want in ("fdc", "off", "core", "pending review", "Credits sold", "100,000", "Last snapshot", "Last dump"):
        assert want in overview, want
    jobs = c.get("/admin/jobs").text
    for want in ("ciqual exploded", "boom: bad zip", "fetch_table", "failed", "snapshot", "fresh", "stale"):
        assert want in jobs, want
    requests_page = c.get("/admin/requests").text
    for want in ("/v1/foods", "401", "p50", "p95", "402", "429", "r1"):
        assert want in requests_page, want
    users = c.get("/admin/users").text
    for want in ("dev@example.com", "500", "dev-live", "dev-old", "revoked", "42", "100,000"):
        assert want in users, want
    assert c.get("/admin/requests", params={"hours": 720}).status_code == 200
    assert c.get("/admin/requests", params={"hours": "junk"}).status_code == 200


# --- actions ---------------------------------------------------------------------------------------------------

def audit() -> list[dict]:
    return rows("select * from admin_action order by id")


def test_grant_credits_needs_the_csrf_token_and_records_who():
    a = account(credits=10)
    c = admin("kirill")
    url = f"/admin/users/{a}/grant"
    assert c.post(url, data={"credits": "50"}).status_code == 403
    assert c.post(url, data={"credits": "50", "csrf": "wrong"}).status_code == 403
    assert account_row(a)["credits"] == 10 and audit() == []
    assert c.get(url).status_code == 405
    r = c.post(url, data={"credits": "50", "csrf": csrf(c)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/admin/users")
    assert account_row(a)["credits"] == 60
    [entry] = audit()
    assert (entry["by"], entry["action"]) == ("kirill", "grant-credits") and str(a) in entry["detail"] and "50" in entry["detail"]
    for bad in ("0", "-5", "x", "", "99999999999"):
        c.post(url, data={"credits": bad, "csrf": csrf(c)})
    assert account_row(a)["credits"] == 60 and len(audit()) == 1


def test_a_csrf_token_of_another_session_is_refused():
    a = account(credits=10)
    other = csrf(admin("someone"))
    c = admin("kirill")
    assert c.post(f"/admin/users/{a}/grant", data={"credits": "5", "csrf": other}).status_code == 403
    assert account_row(a)["credits"] == 10


def test_set_unlimited_on_and_off():
    a = account()
    c = admin()
    url = f"/admin/users/{a}/unlimited"
    assert c.post(url, data={"on": "1"}).status_code == 403
    assert not account_row(a)["unlimited"]
    assert c.post(url, data={"on": "1", "csrf": csrf(c)}, follow_redirects=False).status_code == 303
    assert account_row(a)["unlimited"]
    c.post(url, data={"on": "0", "csrf": csrf(c)})
    assert not account_row(a)["unlimited"]
    assert [e["action"] for e in audit()] == ["set-unlimited", "set-unlimited"]


def test_revoke_a_key_stops_it_working():
    from fooddb import auth

    a = account(credits=5)
    token = auth.create("victim", ["read"], account_id=a)
    kid = key_row("victim")["id"]
    assert client(token).get("/v1/foods", params={"q": "hummus"}).status_code == 200
    c = admin("kirill")
    assert c.post(f"/admin/keys/{kid}/revoke", data={}).status_code == 403
    assert c.post(f"/admin/keys/{kid}/revoke", data={"csrf": csrf(c)}, follow_redirects=False).status_code == 303
    assert key_row("victim")["revoked_at"] is not None
    assert client(token).get("/v1/foods", params={"q": "hummus"}).status_code == 401
    assert [(e["by"], e["action"]) for e in audit()] == [("kirill", "revoke-key")]


def test_an_admin_cannot_revoke_the_key_of_their_own_session():
    c = admin("kirill")
    r = c.post(f"/admin/keys/{key_row('kirill')['id']}/revoke", data={"csrf": csrf(c)}, follow_redirects=False)
    assert r.status_code == 303 and key_row("kirill")["revoked_at"] is None and audit() == []


def test_run_now_queues_a_fetch_once_and_a_snapshot():
    from sqlalchemy import text

    from fooddb.db import engine

    c = admin("kirill")
    with engine().begin() as conn:
        conn.execute(text("delete from pq_tasks"))
    assert c.post("/admin/jobs/run", data={"fetcher": "ciqual"}).status_code == 403
    for _ in range(2):
        assert c.post("/admin/jobs/run", data={"fetcher": "ciqual", "csrf": csrf(c, "jobs")}, follow_redirects=False).status_code == 303
    for fetcher in ("snapshot", "no-such"):
        assert c.post("/admin/jobs/run", data={"fetcher": fetcher, "csrf": csrf(c, "jobs")}, follow_redirects=False).status_code == 303
    with engine().connect() as conn:
        queued = conn.execute(text("select name, payload->'kwargs' as kw from pq_tasks where status = 'PENDING' order by id")).all()
    assert [(n, kw) for n, kw in queued] == [("fooddb.jobs:fetch_table", {"source": "ciqual"}), ("fooddb.jobs:build_snapshot", {})]
    assert [e["action"] for e in audit()] == ["run-now", "run-now"] and "ciqual" in audit()[0]["detail"]


@pytest.mark.parametrize("path,data", [("/admin/users/1/grant", {"credits": "5"}), ("/admin/users/1/unlimited", {"on": "1"}),
                                       ("/admin/keys/1/revoke", {}), ("/admin/jobs/run", {"fetcher": "ciqual"})])
def test_every_action_is_refused_without_an_admin_session(path, data):
    a = account(credits=10)
    assert a == 1
    r = client().post(path, data=data, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/admin/login")
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("review")}).status_code == 400
    assert c.post(path, data=data, follow_redirects=False).status_code == 302
    assert account_row(a)["credits"] == 10 and audit() == []


def test_a_session_whose_admin_key_was_revoked_is_refused():
    from fooddb import auth

    a = account(credits=10)
    c = admin("gone")
    token = csrf(c)
    auth.revoke("gone")
    r = c.post(f"/admin/users/{a}/grant", data={"credits": "5", "csrf": token}, follow_redirects=False)
    assert r.status_code == 302 and account_row(a)["credits"] == 10
