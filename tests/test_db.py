"""Ingest → resolver → API against a real Postgres. Runs only under `./dev test`, which points
FOODDB__BACKEND__DATABASE_URL at this worktree's __test database; skipped otherwise, loudly."""

import os
from datetime import UTC, datetime

import pytest

TEST_URL = os.environ.get("FOODDB_TEST_DATABASE_URL")
# The suite truncates tables, so it runs only against a database whose name says it is a test one.
pytestmark = pytest.mark.skipif(
    not TEST_URL or os.environ.get("FOODDB__BACKEND__DATABASE_URL") != TEST_URL or not TEST_URL.endswith("__test"),
    reason="database suite: run `./dev test` (needs this worktree's test database)",
)


@pytest.fixture(autouse=True)
def clean():
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().begin() as conn:
        conn.execute(text("truncate food, observation, fetch_run, product, snapshot, snapshot_value, fetcher_check restart identity cascade"))


def client():
    from fastapi.testclient import TestClient

    from fooddb.api import app

    return TestClient(app)


def product(record_id: str, include: str | None = None) -> dict:
    r = client().get(f"/v1/records/{record_id}", params={"include": include} if include else {})
    assert r.status_code == 200, r.text
    return r.json()


def rec(**kw):
    from fooddb.ingest import Record

    base = dict(id="fdc:1", source="fdc", layer="core", licence="CC0-1.0", name="Hummus, commercial",
                observed_at=datetime(2026, 1, 1, tzinfo=UTC), values={"ENERC_KCAL": 229.0, "PROCNT": 7.4})
    return Record(**base | kw)


def test_ingest_is_idempotent_and_logged():
    from fooddb import ingest

    assert ingest.run("t", "r1", [rec()]) == (1, 2)
    assert ingest.run("t", "r1", [rec()]) == (1, 0)  # same observations again: nothing new
    assert ingest.already_done("t", "r1")


def test_resolver_serves_newest_value_with_its_source_and_licence():
    from fooddb import ingest

    ingest.run("t", "r1", [rec()])
    ingest.run("t", "r2", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values={"ENERC_KCAL": 230.0, "PROCNT": 7.5})])
    kcal = product("fdc:1")["per_100"]["ENERC_KCAL"]
    assert (kcal["value"], kcal["basis"], kcal["source"], kcal["licence"]) == (230, "100g", "fdc", "CC0-1.0")


def test_api_keeps_off_layer_out_unless_asked():
    from fastapi.testclient import TestClient

    from fooddb import ingest
    from fooddb.api import app

    ingest.run("t", "r1", [rec(), rec(id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0",
                                      gtin14="04006381333931", name="Hummus classic")])
    c = TestClient(app)
    names = [i["name"] for i in c.get("/v1/foods", params={"q": "hummus"}).json()["items"]]
    assert names == ["Hummus, commercial"]
    assert c.get("/v1/products/4006381333931").status_code == 404
    item = c.get("/v1/products/4006381333931", params={"include": "off"}).json()["items"][0]
    assert item["per_100"]["ENERC_KCAL"]["licence"] == "ODbL-1.0"
    assert c.get("/v1/products/123").status_code == 422


def test_product_and_record_lookups_keep_off_layer_out_unless_asked():
    from fooddb import ingest

    ingest.run("t", "r1", [rec(id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0",
                               gtin14="04006381333931", name="Hummus classic")])
    c = client()
    assert c.get("/v1/records/off:04006381333931").status_code == 404
    p = product("off:04006381333931", include="off")
    assert p["per_100"]["ENERC_KCAL"]["licence"] == "ODbL-1.0"
    assert c.get(f"/v1/foods/{p['id']}").status_code == 404
    assert c.get(f"/v1/foods/{p['id']}", params={"include": "off"}).status_code == 200


def test_run_that_ingests_nothing_fails_and_is_retried():
    from fooddb import ingest

    with pytest.raises(ingest.EmptyRun):
        ingest.run("t", "empty", [])
    assert not ingest.already_done("t", "empty")


def test_older_record_does_not_roll_food_back():
    from fooddb import ingest

    ingest.run("t", "new", [rec(name="Hummus, new recipe", observed_at=datetime(2026, 6, 1, tzinfo=UTC))])
    ingest.run("t", "old", [rec(name="Hummus, old recipe", observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                                values={"ENERC_KCAL": 100.0, "PROCNT": 1.0})])
    p = product("fdc:1")
    assert p["name"] == "Hummus, new recipe"
    assert p["per_100"]["ENERC_KCAL"]["value"] == 229


def test_search_finds_a_word_inside_a_long_name():
    from fastapi.testclient import TestClient

    from fooddb import ingest
    from fooddb.api import app

    ingest.run("t", "r1", [rec(id="fdc:2", name="Beans, snap, green, canned, regular pack, drained solids")])
    c = TestClient(app)
    assert [i["records"] for i in c.get("/v1/foods", params={"q": "beans"}).json()["items"]] == [["fdc:2"]]
    assert c.get("/v1/foods", params={"q": "beans", "limit": 0}).status_code == 422


@pytest.mark.parametrize("barcode", [
    "²²²²²²²²",       # unicode digits: used to crash with a 500
    "0400000000008",  # GTIN-13 prefix 04: restricted, in-store use
    "9800000000007",  # GTIN-13 prefix 98: coupons
])
def test_product_lookup_rejects_non_global_barcodes(barcode):
    from fastapi.testclient import TestClient

    from fooddb.api import app

    assert TestClient(app).get(f"/v1/products/{barcode}").status_code == 422


def test_hard_killed_run_is_marked_failed_on_the_next_attempt():
    import subprocess
    import sys

    from fooddb import ingest

    # pq kills a timed-out task with os._exit: no except/finally runs, the row stays "running".
    code = (
        "import os\nfrom tests.test_db import rec\nfrom fooddb import ingest\n"
        "def recs():\n    yield rec()\n    os._exit(124)\n"
        "ingest.run('t', 'killed', recs(), batch=1)\n"
    )
    assert subprocess.run([sys.executable, "-c", code], env=os.environ).returncode == 124
    assert [r["status"] for r in ingest.runs("t", "killed")] == ["running"]

    ingest.run("t", "killed", [rec()])
    assert [r["status"] for r in ingest.runs("t", "killed")] == ["failed", "done"]


def test_full_batch_with_many_nutrients_stays_under_postgres_parameter_limit():
    from fooddb import ingest

    many = {f"N{i}": float(i) for i in range(25)}  # vitamins and minerals will get us here
    records = [rec(id=f"fdc:{i}", values=many) for i in range(500)]
    assert ingest.run("t", "wide", records) == (500, 500 * 25)


def test_values_failing_checks_wait_for_review_while_the_last_good_ones_serve():
    from fooddb import ingest

    ingest.run("t", "good", [rec()])
    typo = {"ENERC_KCAL": 2290.0, "PROCNT": 7.4, "FAT": 17.1, "CHOCDF": 14.9}  # 10x kcal typo
    ingest.run("t", "typo", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=typo)])
    p = product("fdc:1")
    assert p["per_100"]["ENERC_KCAL"]["value"] == 229
    assert ("fdc:1", "ENERC_KCAL", 2290) in [(r["record"], r["nutrient"], r["value"]) for r in ingest.pending()]


def test_unchanged_values_are_not_stored_again_and_dropped_fields_are_withdrawn():
    from fooddb import ingest

    ingest.run("t", "v1", [rec(values={"ENERC_KCAL": 229.0, "NA": 438.0})])
    # A newer edit (say, a photo) that keeps kcal and drops sodium: one row, the withdrawal.
    assert ingest.run("t", "v2", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values={"ENERC_KCAL": 229.0})]) == (1, 1)
    per_100 = product("fdc:1")["per_100"]
    assert per_100["ENERC_KCAL"]["value"] == 229
    assert "NA" not in per_100


HUMMUS = {"ENERC_KCAL": 229.0, "PROCNT": 7.35, "FAT": 17.1, "CHOCDF": 14.9}


def test_matching_merges_records_of_one_food_across_sources_and_keeps_others_apart():
    from fooddb import ingest, jobs

    ingest.run("t", "r1", [
        rec(id="fdc:1", name="Hummus, commercial", values=HUMMUS),
        rec(id="fdc:2", name="Hummus, commercial", values=HUMMUS | {"ENERC_KCAL": 233.0}),
        rec(id="fdc:3", name="Beans, snap, green, raw",
            values={"ENERC_KCAL": 31.0, "PROCNT": 1.8, "FAT": 0.2, "CHOCDF": 7.0}),
    ])
    jobs.match_products()
    a, b, beans = product("fdc:1"), product("fdc:2"), product("fdc:3")
    assert a["id"] == b["id"] and sorted(a["records"]) == ["fdc:1", "fdc:2"]
    assert beans["id"] != a["id"]


def test_matching_joins_a_barcode_across_sources_and_the_trusted_source_wins():
    from fooddb import ingest, jobs

    code = "04006381333931"
    ingest.run("t", "r1", [
        rec(id="off:" + code, source="off", layer="off", licence="ODbL-1.0", gtin14=code,
            name="Hummus Classic", brand="Acme", values=HUMMUS | {"ENERC_KCAL": 240.0}),
        rec(id="fdc:9", gtin14=code, name="ACME, HUMMUS CLASSIC", brand="Acme", values=HUMMUS),
    ])
    jobs.match_products()
    p = product("fdc:9", include="off")
    assert sorted(p["records"]) == ["fdc:9", "off:" + code]
    assert p["per_100"]["ENERC_KCAL"]["source"] == "fdc"  # USDA outranks OFF
    # Without include=off the same product answers from core only.
    assert product("fdc:9")["records"] == ["fdc:9"]


def test_matching_keeps_variants_with_different_barcodes_or_salt_apart():
    from fooddb import ingest, jobs

    juice = {"ENERC_KCAL": 45.0, "PROCNT": 0.3, "FAT": 0.1, "CHOCDF": 10.5}
    carrots = {"ENERC_KCAL": 35.0, "PROCNT": 0.8, "FAT": 0.2, "CHOCDF": 8.2}
    ingest.run("t", "r1", [
        # Two flavours of one brand: different GTINs are different trade items.
        rec(id="off:03256220000000", source="off", layer="off", licence="ODbL-1.0", gtin14="03256220000000",
            name="Pomme Poire sans sucres ajoutés", brand="Auchan", values=juice),
        rec(id="off:03256220000017", source="off", layer="off", licence="ODbL-1.0", gtin14="03256220000017",
            name="Pomme Pêche sans sucres ajoutés", brand="Auchan", values=juice),
        # Same food, salted and unsalted: sodium tells them apart.
        rec(id="fdc:11", name="Carrots, cooked, boiled, drained, without salt", values=carrots | {"NA": 58.0}),
        rec(id="fdc:12", name="Carrots, cooked, boiled, drained, with salt", values=carrots | {"NA": 302.0}),
    ])
    jobs.match_products()
    assert product("off:03256220000000", "off")["id"] != product("off:03256220000017", "off")["id"]
    assert product("fdc:11")["id"] != product("fdc:12")["id"]


def test_matching_keeps_generic_variants_that_differ_by_a_word_apart():
    from fooddb import ingest, jobs

    pepper = {"ENERC_KCAL": 27.0, "PROCNT": 1.0, "FAT": 0.2, "CHOCDF": 6.3, "NA": 2.0}
    ingest.run("t", "r1", [
        rec(id="fdc:21", name="Peppers, bell, red, raw", values=pepper),
        rec(id="fdc:22", name="Peppers, bell, yellow, raw", values=pepper),
        rec(id="fdc:23", name="Peppers, bell, red, raw", values=pepper | {"ENERC_KCAL": 26.0}),  # same food, other dataset
    ])
    jobs.match_products()
    assert product("fdc:21")["id"] == product("fdc:23")["id"]
    assert product("fdc:21")["id"] != product("fdc:22")["id"]


def test_matching_keeps_a_branded_product_apart_from_the_generic_food():
    from fooddb import ingest, jobs

    butter = {"ENERC_KCAL": 717.0, "PROCNT": 0.9, "FAT": 81.1, "CHOCDF": 0.1, "NA": 643.0}
    ingest.run("t", "r1", [
        rec(id="fdc:31", name="Butter, salted", values=butter),
        rec(id="fdc:32", name="BUTTER SALTED", brand="Land O Lakes", values=butter),
    ])
    jobs.match_products()
    assert product("fdc:31")["id"] != product("fdc:32")["id"]


def test_off_file_is_ingested_line_by_line_from_disk(tmp_path):
    import gzip
    import json

    from fooddb.fetchers import off

    products = [
        {"code": "4006381333931", "product_name": "Hummus", "last_modified_t": 1790000000,
         "nutriments": {"energy-kcal_100g": 229, "proteins_100g": 7.4}},
        {"code": "5449000000996", "product_name": "Cola", "last_modified_t": 1790000000,
         "nutrition": {"aggregated_set": {"per": "100ml", "nutrients": {"energy-kj": {"value": 180, "unit": "kJ"}}}}},
    ]
    path = tmp_path / "dump.jsonl.gz"
    with gzip.open(path, "wt") as f:
        f.writelines(json.dumps(p) + "\n" for p in products)
    assert off.load(path, fetcher="off-test", ref="dump-1") == (2, 3)
    assert product("off:05449000000996", "off")["per_100"]["ENERC_KCAL"]["basis"] == "100ml"


def test_api_serves_the_latest_snapshot_and_pins_an_older_one():
    from datetime import date

    from fooddb import ingest, snapshot

    ingest.run("t", "r1", [rec()])
    snapshot.build(date(2026, 10, 1))
    ingest.run("t", "r2", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values={"ENERC_KCAL": 231.0, "PROCNT": 7.4})])
    assert product("fdc:1")["per_100"]["ENERC_KCAL"]["value"] == 229  # not live until the next build
    snapshot.build(date(2026, 10, 2))
    assert product("fdc:1")["per_100"]["ENERC_KCAL"]["value"] == 231
    pinned = client().get("/v1/records/fdc:1", params={"snapshot": "2026-10-01"}).json()
    assert pinned["per_100"]["ENERC_KCAL"]["value"] == 229 and pinned["snapshot"] == "2026-10-01"
    assert client().get("/v1/records/fdc:1", params={"snapshot": "2026-09-01"}).status_code == 404


def test_health_reports_stale_and_fresh_fetchers():
    from datetime import timedelta

    from fooddb import health

    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    health.checked("off-delta", at=now - timedelta(hours=2))
    health.checked("fdc-foundation", at=now - timedelta(days=20))
    report = health.report(now=now)
    assert report["fetchers"]["off-delta"]["fresh"] is True
    assert report["fetchers"]["fdc-foundation"]["fresh"] is False
    assert report["fetchers"]["fdc-sr_legacy"]["fresh"] is False  # never checked
    assert report["ok"] is False
    r = client().get("/healthz")
    assert r.status_code == 503 and "fetchers" in r.json()


def call(tool: str, **args):
    import anyio
    from mcp import Client

    from fooddb.api import mcp

    async def go():
        async with Client(mcp) as c:
            return await c.call_tool(tool, args)

    return anyio.run(go)


def test_mcp_tools_serve_the_api_reads_and_keep_off_layer_out_unless_asked():
    from fooddb import ingest

    ingest.run("t", "r1", [rec(), rec(id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0",
                                      gtin14="04006381333931", name="Hummus classic")])
    found = call("search_foods", q="hummus").structured_content["items"]
    assert [i["name"] for i in found] == ["Hummus, commercial"]
    assert found[0]["per_100"]["ENERC_KCAL"]["licence"] == "CC0-1.0"

    core = call("get_product_by_barcode", barcode="4006381333931")
    assert core.is_error and "not found in core" in core.content[0].text
    item = call("get_product_by_barcode", barcode="4006381333931", include_off=True).structured_content["items"][0]
    assert item["per_100"]["ENERC_KCAL"]["licence"] == "ODbL-1.0"
    assert call("get_product_by_barcode", barcode="123").is_error

    p = call("get_record_product", record_id="fdc:1").structured_content
    assert call("get_food", product_id=p["id"]).structured_content["records"] == ["fdc:1"]
    assert call("get_food", product_id=999999).is_error
    assert call("search_foods", q="h").is_error
    assert "fetchers" in call("health_report").structured_content


class OneOffQueue:
    """pq's one-off order: highest priority first, then oldest. An upsert on a client_id moves the
    task to the back, as pq resets its run_at."""

    def __init__(self):
        self.tasks = {}

    def schedule(self, *args, **kwargs):
        pass

    def upsert(self, fn, *, client_id, priority=50, **kwargs):  # 50 = Priority.NORMAL, pq's default
        self.tasks.pop(client_id, None)
        self.tasks[client_id] = (priority, fn, kwargs)

    def drain(self) -> list[str]:
        ran = []
        while self.tasks:
            _, fn, kwargs = self.tasks.pop(max(self.tasks, key=lambda c: self.tasks[c][0]))
            fn(**kwargs)
            ran.append(fn.__name__)
        return ran


def test_first_boot_serves_off_values_without_a_manual_snapshot(monkeypatch):
    from fooddb import ingest, jobs
    from fooddb.fetchers import fdc, off

    q = OneOffQueue()
    monkeypatch.setattr(jobs, "queue", lambda: q)
    monkeypatch.setattr(fdc, "fetch", lambda dataset, force=False: ingest.run(
        f"fdc-{dataset}", "r1", [rec(id=f"fdc:{dataset}")]))
    deltas = iter(["d1", "d2"])

    def off_fetch(max_files=1):
        name = next(deltas)
        foods, obs = ingest.run(off.FETCHER, name, [rec(
            id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0", gtin14="04006381333931",
            name="Chocolate hazelnut spread", values={"ENERC_KCAL": 539.0 if name == "d1" else 540.0})])
        return [(name, foods, obs)]

    monkeypatch.setattr(off, "fetch", off_fetch)

    jobs.schedule()
    assert q.drain() == ["fetch_fdc", "fetch_fdc", "match_products", "build_snapshot"]
    jobs.fetch_off_deltas()  # the periodic delta: pq runs it after every one-off task
    assert q.drain() == ["match_products", "build_snapshot"]
    kcal = product("off:04006381333931", "off")["per_100"]["ENERC_KCAL"]
    assert (kcal["value"], kcal["source"]) == (539, "off")

    jobs.fetch_off_deltas()  # later deltas wait for the nightly snapshot
    assert q.drain() == ["match_products"]
    assert product("off:04006381333931", "off")["per_100"]["ENERC_KCAL"]["value"] == 539
