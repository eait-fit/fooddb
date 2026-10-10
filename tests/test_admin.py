"""The admin panel's look and navigation: login page, cookie, menu sections, dashboard, list filters and row actions. Database suite."""

import json
import re
from datetime import UTC, datetime

from tests.test_db import HUMMUS, TYPO, clean, client, ingest_typo, key, pending_id, pytestmark, rec, wrongly_merged_hummus  # noqa: F401
from tests.test_ops import admin, csrf, rows, seed


def test_the_login_page_asks_for_an_api_key_and_sets_a_strict_session_cookie():
    page = client().get("/admin/login")
    assert page.status_code == 200 and "API key" in page.text and 'type="text"' not in page.text
    r = client().post("/admin/login", data={"username": "", "password": key("admin", name="kirill")}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 302 and "samesite=strict" in cookie and "httponly" in cookie and f"max-age={8 * 3600}" in cookie
    assert client().post("/admin/login", data={"username": "", "password": "fdb_nope"}).status_code == 400


def test_the_landing_page_is_the_overview_dashboard_after_login():
    assert client().get("/admin/", follow_redirects=False).headers["location"].endswith("/admin/login")
    r = admin().get("/admin/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/admin/overview")


def test_the_admin_is_not_served_without_the_secret(monkeypatch, caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fooddb import admin as admin_module

    monkeypatch.delenv("FOODDB__BACKEND__SECRET_KEY")
    app = FastAPI()
    admin_module.mount(app)
    assert TestClient(app).get("/admin/login").status_code == 404 and "/admin is not served" in caplog.text


def test_every_page_carries_the_admin_style_and_the_three_menu_sections():
    c = admin()
    for path in ("/admin/overview", "/admin/review", "/admin/observation/list", "/admin/merge-log/list", "/admin/users",
                 "/admin/account/list", "/admin/purchase/list"):
        page = c.get(path).text
        assert "--fd-accent" in page, path  # base.html adds the CSS to model views too
        for section in ("Review", "Platform", "Customers"):
            assert f'data-sqladmin-menu-category="{section}"' in page, (path, section)
        for link in ("/admin/overview", "/admin/review", "/admin/observation/list", "/admin/merge-log/list", "/admin/jobs",
                     "/admin/requests", "/admin/users", "/admin/account/list", "/admin/purchase/list"):
            assert f'href="http://testserver{link}"' in page, (path, link)


def test_the_dashboard_counts_pending_values_jobs_requests_and_credits():
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().begin() as conn:
        conn.execute(text("truncate pq_tasks"))  # the queue outlives the other tests' tables
    seed()
    c = admin()
    for _ in range(3):
        client(key("read", name=f"r{_}")).get("/v1/foods", params={"q": "hummus"})
    page = c.get("/admin/overview").text
    assert re.search(r'Values pending review</div><div class="value">2</div>', page) and "1 record waits for a decision" in page
    assert re.search(r'Jobs</div><div class="value">0 active</div>.*?1 failed, 0 completed', page, re.S)
    assert 'class="chart"' in page and "requests, " in page  # one <title> per hourly bar
    assert 'href="http://testserver/admin/review?check=energy-mismatch"' in page  # the needs-attention list links to the Review filter
    assert "fetch_table" in page and "Accounts</div>" in page and "Credits outstanding" in page and "500" in page


def test_a_quiet_hour_is_an_empty_bar_not_a_gap_in_the_chart():
    from fooddb import ops

    assert len(ops._hourly(24)) == 25 and all(b["n"] == 0 and b["pct"] == 0 for b in ops._hourly(24))
    assert len(ops._hourly(168)) == 8 and len(ops._hourly(720)) == 31
    client().get("/v1/foods")
    assert sum(b["n"] for b in ops._hourly(24)) == 1


def test_pending_values_filter_lists_only_pending_values_and_filters_the_list():
    from fooddb import ingest

    ingest_typo()
    ingest.run("t", "table", [rec(id="ciqual:1", source="ciqual", name="Hummus, table", values={"ENERC_KCAL": 229.0, "PROCNT": 7.4})])
    c = admin()
    page = c.get("/admin/observation/list").text
    assert "source=fdc" in page and "source=ciqual" not in page and "nutrient=ENERC_KCAL" in page
    assert "2290" in page
    assert "2290" not in c.get("/admin/observation/list", params={"source": "ciqual"}).text
    assert "2290" in c.get("/admin/observation/list", params={"source": "fdc", "nutrient": "ENERC_KCAL"}).text
    assert "2290" in c.get("/admin/observation/list", params={"search": "ENERC"}).text


def test_a_pending_row_has_accept_and_reject_buttons_that_return_to_the_same_filtered_list():
    from sqlalchemy import text

    from fooddb.db import engine

    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    c = admin()
    page = c.get("/admin/observation/list", params={"source": "fdc"}).text
    back = "%2Fadmin%2Fobservation%2Flist%3Fsource%3Dfdc"
    assert f"/admin/observation/action/accept?pks={obs}&next={back}" in page
    assert f"/admin/observation/action/reject?pks={obs}&next={back}" in page
    r = c.get(f"/admin/observation/action/reject?pks={obs}&next={back}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/admin/observation/list?source=fdc"
    with engine().connect() as conn:
        assert tuple(conn.execute(text("select status, reviewed_by from observation where id = :i"), {"i": obs}).one()) == ("rejected", "ops")
    assert "Rejected ENERC_KCAL 2290 kcal/100g" in c.get("/admin/observation/list").text  # the toast, once
    assert "2290" not in c.get("/admin/observation/list").text


def test_the_merge_log_filters_by_kind_and_a_merge_row_has_a_split_button():
    survivor, merged_away = wrongly_merged_hummus()
    c = admin()
    [merge] = rows("select id from merge_log where kind = 'merge'")
    page = c.get("/admin/merge-log/list").text
    assert f"/admin/merge-log/action/split?pks={merge['id']}" in page and "fdc:2" in page and "0.9" in page
    assert c.get(f"/admin/merge-log/action/split?pks={merge['id']}", follow_redirects=False).status_code == 302
    page = c.get("/admin/merge-log/list").text
    assert page.count("action/split?pks=") == 1  # the new split row has no button of its own
    assert "action/split?pks=" not in c.get("/admin/merge-log/list", params={"kind": "split"}).text
    assert "action/split?pks=" in c.get("/admin/merge-log/list", params={"kind": "merge"}).text


def test_accounts_and_purchases_show_formatted_numbers_and_filter():
    seed()
    from fooddb import accounts

    accounts.ensure("big@example.com")
    c = admin()
    accounts_page = c.get("/admin/account/list").text
    assert "dev@example.com" in accounts_page and "big@example.com" in accounts_page and "500" in accounts_page
    from tests.test_ops import account_row

    from fooddb import ops

    ops.set_unlimited(account_row(1)["id"], True, "kirill")
    only = c.get("/admin/account/list", params={"unlimited": "true"}).text
    assert "dev@example.com" in only and "big@example.com" not in only and "unlimited</span>" in only
    purchases = c.get("/admin/purchase/list").text
    assert "EUR 29.99" in purchases and "100,000" in purchases and "cs_1" in purchases
    assert "cs_1" in c.get("/admin/purchase/list", params={"search": "cs_"}).text
    for view in ("account", "purchase"):
        assert c.get(f"/admin/{view}/create").status_code in (403, 404)


def test_the_users_and_requests_tables_can_be_sorted_and_filtered_in_the_browser():
    seed()
    c = admin()
    users = c.get("/admin/users").text
    assert 'id="accounts" data-sortable' in users and 'data-filter="accounts"' in users and "<details>" in users
    requests_page = c.get("/admin/requests").text
    for table in ("bykey", "routes", "recent"):
        assert f'id="{table}" data-sortable' in requests_page and f'data-filter="{table}"' in requests_page
    jobs = c.get("/admin/jobs").text
    for table in ("fresh", "queue", "schedules", "runs"):
        assert f'id="{table}" data-sortable' in jobs


def test_undo_puts_back_only_the_values_this_reviewer_decided_and_that_are_still_decided():
    from fooddb import review

    ingest_typo()
    kcal, sugar = pending_id("ENERC_KCAL"), pending_id("SUGAR")
    review.decide(kcal, "accept", "ops")
    review.decide(sugar, "reject", "agent")
    assert review.undo([kcal, sugar], "ops") == 1
    assert rows("select status, reviewed_by, reviewed_at, review_note from observation where id = :i", i=kcal) == [
        {"status": "pending", "reviewed_by": None, "reviewed_at": None, "review_note": None}]
    assert rows("select status, reviewed_by from observation where id = :i", i=sugar) == [{"status": "rejected", "reviewed_by": "agent"}]
    assert review.undo([kcal, sugar], "ops") == 0  # one is pending again, the other is not the reviewer's


def test_a_decision_from_the_review_page_shows_a_toast_with_undo_that_returns_to_the_same_page():
    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    c = admin()
    back = "/admin/review%3Fsource%3Dfdc%26offset%3D0"
    r = c.get(f"/admin/observation/action/accept?pks={obs}&next={back}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/admin/review?source=fdc&offset=0"
    page = c.get(r.headers["location"]).text
    assert "Accepted ENERC_KCAL 2290 kcal/100g · Hummus, commercial" in page
    assert f'name="ids" value="{obs}"' in page and f"/admin/review/undo?next={back}" in page
    assert "Undo" not in c.get(r.headers["location"]).text  # the toast is shown once
    assert c.post(f"/admin/review/undo?next={back}", data={"ids": str(obs), "csrf": "wrong"}).status_code == 403
    r = c.post(f"/admin/review/undo?next={back}", data={"ids": str(obs), "csrf": csrf(c)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/review?source=fdc&offset=0"
    assert "Undone: 1 values back to pending" in c.get(r.headers["location"]).text
    assert rows("select status from observation where id = :i", i=obs) == [{"status": "pending"}]
    [logged] = rows("select \"by\", action, detail from admin_action")
    assert (logged["by"], logged["action"], json.loads(logged["detail"])) == ("ops", "review-undo", {"observations": [obs], "reverted": 1})


def test_accept_all_asks_for_confirmation_and_names_the_count_without_trusting_the_product_name():
    from fooddb import ingest

    name = '"><img src=x onerror=alert(1)>'
    ingest.run("t", "good", [rec(name=name, values=HUMMUS)])
    ingest.run("t", "typo", [rec(name=name, observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=TYPO)])
    page = admin().get("/admin/review").text
    assert "Accept all 2" in page and "btn-outline-success" in page and "Accept all pending" not in page
    assert "onclick='return confirm(\"Accept all 2 pending values of \\\"\\u003e\\u003cimg" in page
    assert "<img src=x" not in page


def test_the_review_column_names_its_snapshot_day_and_a_record_after_it_is_not_in_the_snapshot_yet():
    from fooddb import ingest, snapshot

    ingest_typo()
    c = admin()
    assert "Served now" in c.get("/admin/review").text  # no snapshot yet: the live values
    snapshot.build()
    page = c.get("/admin/review").text
    assert f"Served in snapshot {snapshot.today()}" in page and "not in snapshot yet" not in page and ">none<" in page
    ingest.run("t", "late", [rec(id="fdc:2", name="Late", values=TYPO)])
    assert "not in snapshot yet" in c.get("/admin/review").text
