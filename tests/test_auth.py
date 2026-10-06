"""API keys, scopes and rate limits on REST, MCP over HTTP and the admin. Database suite."""

import hashlib
import re

import pytest

from tests.test_db import clean, client, ingest_typo, key, pending_id, pytestmark, rec  # noqa: F401

DECISION = {"decision": "reject", "by": "tester"}


@pytest.fixture
def reads_need_a_key(monkeypatch):
    monkeypatch.setenv("FOODDB__BACKEND__REQUIRE_KEY_FOR_READS", "true")


def test_every_write_route_needs_a_key():
    from fooddb.api import app

    writes = [(m, re.sub(r"\{[^}]+\}", "1", path)) for path, ops in app.openapi()["paths"].items()
              for m in ops if m not in ("get", "head")]
    assert ("post", "/v1/review/1") in writes
    for method, path in writes:
        assert client().request(method, path, json=DECISION).status_code == 401, (method, path)


def test_review_routes_need_the_review_scope():
    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    read, review = key("read"), key("review")
    for c, want in ((client(), 401), (client(read), 403), (client("fdb_not-a-key"), 401)):
        assert c.get("/v1/review").status_code == want
        assert c.post(f"/v1/review/{obs}", json=DECISION).status_code == want
    assert client(review).get("/v1/review").status_code == 200
    r = client().post(f"/v1/review/{obs}", json=DECISION, headers={"X-API-Key": review})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_reads_are_open_by_default_and_need_a_key_when_configured(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec()])
    assert client().get("/v1/foods", params={"q": "hummus"}).status_code == 200
    assert client("fdb_not-a-key").get("/v1/foods", params={"q": "hummus"}).status_code == 401
    monkeypatch.setenv("FOODDB__BACKEND__REQUIRE_KEY_FOR_READS", "true")
    for path in ("/v1/foods?q=hummus", "/v1/records/fdc:1", "/v1/snapshots"):
        assert client().get(path).status_code == 401, path
        assert client(key("read", name=f"r{path}")).get(path).status_code == 200, path
    assert client(key("review")).get("/v1/records/fdc:1").status_code == 200  # review implies read
    assert client().get("/livez").status_code == 200
    assert client().get("/healthz").status_code == 503  # open, and stale: nothing fetched


def test_rapidapi_proxy_secret_counts_as_read(monkeypatch, reads_need_a_key):
    from fooddb import ingest

    ingest.run("t", "r1", [rec()])
    monkeypatch.setenv("FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET", "s3cret")
    assert client().get("/v1/records/fdc:1", headers={"X-RapidAPI-Proxy-Secret": "s3cret"}).status_code == 200
    assert client().get("/v1/records/fdc:1", headers={"X-RapidAPI-Proxy-Secret": "wrong"}).status_code == 401
    assert client().get("/v1/review", headers={"X-RapidAPI-Proxy-Secret": "s3cret"}).status_code == 403
    monkeypatch.delenv("FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET")
    assert client().get("/v1/records/fdc:1", headers={"X-RapidAPI-Proxy-Secret": ""}).status_code == 401


def test_a_revoked_key_is_refused():
    from fooddb import auth

    k = key("review", name="leaked")
    assert client(k).get("/v1/review").status_code == 200
    assert auth.revoke("leaked")
    assert client(k).get("/v1/review").status_code == 401
    assert not auth.revoke("leaked")


def test_rate_limit_answers_429_with_retry_after(monkeypatch):
    k = key("read", rate_limit=2)
    statuses = [client(k).get("/v1/foods", params={"q": "hummus"}) for _ in range(3)]
    assert [r.status_code for r in statuses] == [200, 200, 429]
    assert 1 <= int(statuses[2].headers["Retry-After"]) <= 60
    monkeypatch.setenv("FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE", "1")
    assert [client().get("/v1/foods", params={"q": "hummus"}).status_code for _ in range(2)] == [200, 429]
    assert client(key("read", name="other")).get("/v1/foods", params={"q": "hummus"}).status_code == 200


def test_keys_are_stored_as_hashes_only():
    from sqlalchemy import text

    from fooddb.db import engine

    k = key("admin")
    assert k.startswith("fdb_")
    with engine().connect() as conn:
        row = conn.execute(text("select * from api_key")).mappings().one()
    assert row["token_hash"] == hashlib.pbkdf2_hmac("sha256", k.encode(), b"test-only-secret", 1000).hex()
    assert row["token_hash"] != hashlib.sha256(k.encode()).hexdigest()
    assert not any(k in str(v) or k[4:] in str(v) for v in row.values())


def test_keys_are_keyed_to_the_server_secret(monkeypatch):
    from fooddb import auth

    k = key("read")
    assert auth.lookup(k) is not None
    monkeypatch.setenv("FOODDB__BACKEND__SECRET_KEY", "another-secret")
    assert auth.lookup(k) is None
    monkeypatch.delenv("FOODDB__BACKEND__SECRET_KEY")
    assert auth.lookup(k) is None
    with pytest.raises(RuntimeError, match="FOODDB__BACKEND__SECRET_KEY"):
        auth.create("no-secret", ["read"])


def test_cli_prints_a_key_once_and_lists_and_revokes_it():
    from typer.testing import CliRunner

    from fooddb.cli import app

    run = CliRunner().invoke
    created = run(app, ["keys", "create", "--name", "eait", "--scope", "read", "--rate-limit", "600"])
    assert created.exit_code == 0, created.output
    token = re.search(r"fdb_\S+", created.output).group()
    assert client(token).get("/v1/snapshots").status_code == 200
    listed = run(app, ["keys", "list"]).output
    assert "eait" in listed and "read" in listed and "600" in listed and token not in listed
    assert run(app, ["keys", "create", "--name", "x", "--scope", "owner"]).exit_code != 0
    assert run(app, ["keys", "revoke", "eait"]).exit_code == 0
    assert run(app, ["keys", "revoke", "eait"]).exit_code != 0
    assert client(token).get("/v1/snapshots").status_code == 401


def test_mcp_over_http_needs_the_review_scope_to_decide(reads_need_a_key):
    import anyio
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    from fooddb.api import app, mcp

    ingest_typo()
    sugar = pending_id("SUGAR")
    assert client().post("/mcp", json={}).status_code == 401
    assert client("fdb_not-a-key").post("/mcp", json={}).status_code == 401

    async def session(token: str):
        h = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:9640",
                               headers={"Authorization": f"Bearer {token}"})
        return Client(streamable_http_client("http://127.0.0.1:9640/mcp", http_client=h))

    async def go():
        async with mcp.session_manager.run():
            async with await session(key("read")) as c:
                assert not (await c.call_tool("get_record_product", {"record_id": "fdc:1"})).is_error
                assert (await c.call_tool("review_queue", {})).is_error
                refused = await c.call_tool("decide_review", {"observation_id": sugar, "decision": "reject", "by": "x"})
                assert refused.is_error and "review" in refused.content[0].text
            async with await session(key("review")) as c:
                assert not (await c.call_tool("review_queue", {})).is_error
                done = await c.call_tool("decide_review", {"observation_id": sugar, "decision": "reject", "by": "x"})
                assert done.structured_content["status"] == "rejected"

    anyio.run(go)


def test_admin_login_takes_only_an_admin_key():
    from sqlalchemy import text

    from fooddb import auth
    from fooddb.db import engine

    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    c = client()
    assert c.get("/admin/observation/list", follow_redirects=False).headers["location"].endswith("/admin/login")
    assert c.get(f"/admin/observation/action/accept?pks={obs}", follow_redirects=False).status_code == 302
    for k in (key("review"), key("read"), "fdb_not-a-key"):
        assert c.post("/admin/login", data={"username": "", "password": k}).status_code == 400
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="ops")},
                  follow_redirects=False).status_code == 302
    assert c.get("/admin/observation/list").status_code == 200
    with engine().connect() as conn:
        assert conn.execute(text("select status from observation where id = :id"), {"id": obs}).scalar() == "pending"
    auth.revoke("ops")
    assert c.get("/admin/observation/list", follow_redirects=False).status_code == 302
