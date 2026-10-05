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
    names = [i["name"]["value"] for i in c.get("/v1/foods", params={"q": "hummus"}).json()["items"]]
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
    assert p["name"]["value"] == "Hummus, new recipe"
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
    from fooddb import review

    assert ("fdc:1", "ENERC_KCAL", 2290) in [
        (i["record"], v["nutrient"], v["value"]) for i in review.queue() for v in i["pending"]]


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


def acme_hummus_in_both_layers() -> str:
    from fooddb import ingest, jobs

    code = "04006381333931"
    ingest.run("t", "r1", [
        rec(id="off:" + code, source="off", layer="off", licence="ODbL-1.0", gtin14=code, name="Hummus Classic",
            brand="Acme", lang="de", serving_text="2 EL (30 g)", serving_g=30.0,
            values=HUMMUS | {"ENERC_KCAL": 240.0, "FIBTG": 6.0}),
        rec(id="fdc:9", gtin14=code, name="ACME, HUMMUS CLASSIC", brand="Acme", values=HUMMUS),
    ])
    jobs.match_products()
    return code


FIELDS = ("name", "brand", "lang", "serving_text", "serving_g", "flags")


def test_every_served_field_carries_the_source_licence_and_record_it_came_from():
    from fooddb import ingest

    code = acme_hummus_in_both_layers()
    fdc = {"source": "fdc", "licence": "CC0-1.0", "record": "fdc:9"}
    for include in (None, "off"):
        p = product("fdc:9", include)
        assert p["name"] == {"value": "ACME, HUMMUS CLASSIC"} | fdc
        assert p["brand"] == {"value": "Acme"} | fdc
        assert p["flags"] == {"value": []} | fdc
        assert p["lang"] is p["serving_text"] is p["serving_g"] is None  # fdc:9 has none: nothing to tag
        assert p["gtin14"] == [{"value": code} | fdc]  # both records carry it: the trusted one tags it
        assert all({"source", "licence"} <= v.keys() for v in p["per_100"].values())
    ingest.run("t", "r2", [rec(id="off:03256220000017", source="off", layer="off", licence="ODbL-1.0",
                               gtin14="03256220000017", name="Pomme Pêche", lang="fr", serving_text="1 gourde",
                               serving_g=90.0, extra_flags=["off-flag"], values={"ENERC_KCAL": 45.0})])
    off = {"source": "off", "licence": "ODbL-1.0", "record": "off:03256220000017"}
    p = product("off:03256220000017", "off")
    assert float(p["serving_g"].pop("value")) == 90 and p["serving_g"] == off
    assert {f: p[f] for f in FIELDS if f != "serving_g"} == {
        "name": {"value": "Pomme Pêche"} | off, "brand": None, "lang": {"value": "fr"} | off,
        "serving_text": {"value": "1 gourde"} | off, "flags": {"value": ["off-flag"]} | off}
    assert p["gtin14"] == [{"value": "03256220000017"} | off]


def test_a_core_response_carries_nothing_from_the_off_layer(monkeypatch):
    acme_hummus_in_both_layers()
    for build in (False, True):
        if build:
            build_on(monkeypatch, "2026-10-01")
        core = client().get("/v1/records/fdc:9")
        assert core.status_code == 200
        assert "ODbL" not in core.text and "off:" not in core.text and "30 g" not in core.text
        assert core.json()["records"] == ["fdc:9"] and "FIBTG" not in core.json()["per_100"]
        assert "ODbL" in client().get("/v1/records/fdc:9", params={"include": "off"}).text


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
    assert off.load(path, fetcher="off-test", ref="dump-1") == (2, 4)  # the cola keeps its kJ and gets kcal
    assert product("off:05449000000996", "off")["per_100"]["ENERC_KCAL"]["basis"] == "100ml"


def build_on(monkeypatch, day: str) -> None:
    from datetime import date

    from fooddb import snapshot

    monkeypatch.setattr(snapshot, "today", lambda: date.fromisoformat(day))
    snapshot.build()


def kcal(record_id: str, **params) -> float:
    r = client().get(f"/v1/records/{record_id}", params=params)
    assert r.status_code == 200, r.text
    return r.json()["per_100"]["ENERC_KCAL"]["value"]


def test_api_serves_the_latest_snapshot_and_pins_an_older_one(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec()])
    build_on(monkeypatch, "2026-10-01")
    ingest.run("t", "r2", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values={"ENERC_KCAL": 231.0, "PROCNT": 7.4})])
    assert kcal("fdc:1") == 229  # not live until the next build
    build_on(monkeypatch, "2026-10-02")
    assert kcal("fdc:1") == 231
    pinned = client().get("/v1/records/fdc:1", params={"snapshot": "2026-10-01"}).json()
    assert pinned["per_100"]["ENERC_KCAL"]["value"] == 229 and pinned["snapshot"] == "2026-10-01"
    assert client().get("/v1/records/fdc:1", params={"snapshot": "2026-09-01"}).status_code == 404


def test_a_day_is_final_once_it_is_over_and_only_today_is_rebuilt(monkeypatch):
    from fooddb import ingest

    def observe(name: str, value: float, month: int) -> None:
        ingest.run("t", name, [rec(observed_at=datetime(2026, month, 1, tzinfo=UTC), values={"ENERC_KCAL": value})])

    observe("r1", 229.0, 1)
    build_on(monkeypatch, "2026-10-01")
    observe("r2", 231.0, 2)
    build_on(monkeypatch, "2026-10-01")  # a same-day rebuild (a fetcher's first data) replaces today
    assert kcal("fdc:1") == kcal("fdc:1", snapshot="2026-10-01") == 231
    observe("r3", 233.0, 3)
    build_on(monkeypatch, "2026-10-02")
    observe("r4", 235.0, 4)
    build_on(monkeypatch, "2026-10-02")
    assert kcal("fdc:1") == 235
    assert kcal("fdc:1", snapshot="2026-10-01") == 231  # 2026-10-01 is over: no build writes it again


def test_a_merge_after_a_snapshot_keeps_the_values_the_snapshot_froze(monkeypatch):
    from fooddb import ingest, jobs

    ingest.run("t", "r1", [
        rec(id="fdc:1", name="Hummus, commercial", values=HUMMUS),
        rec(id="fdc:2", name="Hummus, commercial", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
            values=HUMMUS | {"ENERC_KCAL": 233.0, "FIBTG": 6.0}),
    ])
    survivor, merged_away = product("fdc:1")["id"], product("fdc:2")["id"]
    assert survivor < merged_away
    build_on(monkeypatch, "2026-10-01")
    jobs.match_products()
    for params in ({}, {"snapshot": "2026-10-01"}):
        for pid in (survivor, merged_away):
            r = client().get(f"/v1/foods/{pid}", params=params)
            assert r.status_code == 200, r.text
            p = r.json()
            assert (p["id"], sorted(p["records"])) == (survivor, ["fdc:1", "fdc:2"])
            # As if the merge had come before the build: fdc:2's newer kcal and its fibre.
            assert {n: v["value"] for n, v in p["per_100"].items()} == HUMMUS | {"ENERC_KCAL": 233.0, "FIBTG": 6.0}


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
    assert [i["name"]["value"] for i in found] == ["Hummus, commercial"]
    assert found[0]["name"]["licence"] == "CC0-1.0"
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


TYPO = HUMMUS | {"ENERC_KCAL": 2290.0, "SUGAR": 20.0, "FIBTG": 6.0}  # 10x kcal, sugars over carbs, new fibre


def ingest_typo() -> None:
    from fooddb import ingest

    ingest.run("t", "good", [rec(values=HUMMUS)])
    ingest.run("t", "typo", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=TYPO)])


def pending_id(nutrient: str) -> int:
    from fooddb import review

    return next(v["observation_id"] for i in review.queue() for v in i["pending"] if v["nutrient"] == nutrient)


def test_a_failing_check_holds_back_only_the_fields_it_implicates():
    from fooddb import review

    ingest_typo()
    [item] = review.queue()
    assert item["record"] == "fdc:1" and item["product_id"] == product("fdc:1")["id"]
    assert {v["nutrient"]: v["value"] for v in item["pending"]} == {"ENERC_KCAL": 2290, "SUGAR": 20}
    assert {"energy-mismatch", "sugars-over-carbs"} <= set(item["checks"])
    assert item["served"]["ENERC_KCAL"]["value"] == 229
    per_100 = product("fdc:1")["per_100"]
    assert (per_100["ENERC_KCAL"]["value"], per_100["FIBTG"]["value"]) == (229, 6)  # fibre passed: served
    assert "SUGAR" not in per_100


def test_an_accepted_value_is_served_from_the_next_snapshot(monkeypatch):
    from fooddb import review

    ingest_typo()
    build_on(monkeypatch, "2026-10-01")
    obs = pending_id("ENERC_KCAL")
    r = client().post(f"/v1/review/{obs}", json={"decision": "accept", "by": "tester", "note": "label says so"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["status"], d["reviewed_by"], d["review_note"]) == ("accepted", "tester", "label says so")
    assert d["reviewed_at"]
    assert kcal("fdc:1") == 229  # the snapshot holds until the next build
    build_on(monkeypatch, "2026-10-02")
    assert kcal("fdc:1") == 2290
    assert kcal("fdc:1", snapshot="2026-10-01") == 229
    assert [v["nutrient"] for i in review.queue() for v in i["pending"]] == ["SUGAR"]


def test_a_rejected_value_is_never_served(monkeypatch):
    from fooddb import ingest

    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    assert client().post(f"/v1/review/{obs}", json={"decision": "reject", "by": "tester"}).json()["status"] == "rejected"
    # The source sends the same typo again: it is not stored again, so it does not come back for review.
    ingest.run("t", "typo-again", [rec(observed_at=datetime(2026, 7, 1, tzinfo=UTC), values=TYPO)])
    build_on(monkeypatch, "2026-10-01")
    assert kcal("fdc:1") == 229
    assert client().get("/v1/review").json()["items"][0]["pending"][0]["nutrient"] == "SUGAR"


def test_review_decisions_are_final_and_validated():
    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    c = client()
    assert c.post(f"/v1/review/{obs}", json={"decision": "maybe", "by": "tester"}).status_code == 422
    assert c.post(f"/v1/review/{obs}", json={"decision": "accept"}).status_code == 422  # who decided is required
    assert c.post(f"/v1/review/{obs}", json={"decision": "accept", "by": "tester"}).status_code == 200
    assert c.post(f"/v1/review/{obs}", json={"decision": "reject", "by": "tester"}).status_code == 409
    assert c.post("/v1/review/999999", json={"decision": "accept", "by": "tester"}).status_code == 404


def test_mcp_agents_work_the_same_review_queue():
    ingest_typo()
    [item] = call("review_queue").structured_content["items"]
    sugar = next(v["observation_id"] for v in item["pending"] if v["nutrient"] == "SUGAR")
    assert call("decide_review", observation_id=sugar, decision="reject", by="agent").structured_content["status"] == "rejected"
    assert call("decide_review", observation_id=sugar, decision="accept", by="agent").is_error
    assert [v["nutrient"] for v in call("review_queue").structured_content["items"][0]["pending"]] == ["ENERC_KCAL"]


def test_admin_lists_pending_values_and_accepts_them():
    from sqlalchemy import text

    from fooddb.db import engine

    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    c = client()
    page = c.get("/admin/observation/list")
    assert page.status_code == 200 and "2290" in page.text and "FIBTG" not in page.text
    assert c.get(f"/admin/observation/action/accept?pks={obs}", follow_redirects=False).status_code == 302
    with engine().connect() as conn:
        row = conn.execute(text("select status, reviewed_by from observation where id = :id"), {"id": obs}).one()
    assert tuple(row) == ("accepted", "admin")


def merge(*record_ids: str) -> None:
    """Put records in one product the way the match job does: the lowest product id survives."""
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().begin() as conn:
        pids = sorted(set(conn.execute(text("select product_id from food where id = any(:ids)"),
                                       {"ids": list(record_ids)}).scalars()))
        conn.execute(text("update food set product_id = :s where product_id = any(:o)"), {"s": pids[0], "o": pids[1:]})
        conn.execute(text("update product set merged_into = :s where id = any(:o)"), {"s": pids[0], "o": pids[1:]})


def served(record_id: str, include: str | None = None) -> tuple[float, str]:
    v = product(record_id, include)["per_100"]["ENERC_KCAL"]
    return v["value"], v["source"]


def kcal_record(id: str, source: str, value: float, year: int):
    return rec(id=id, source=source, layer="off" if source == "off" else "core",
               licence="ODbL-1.0" if source == "off" else "CC0-1.0",
               observed_at=datetime(year, 1, 1, tzinfo=UTC), values={"ENERC_KCAL": value})


def test_a_crowd_value_much_newer_than_a_table_value_wins(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [
        kcal_record("fdc:1", "fdc", 229.0, 2018), kcal_record("off:1", "off", 260.0, 2026),  # 8 years apart
        kcal_record("fdc:2", "fdc", 229.0, 2025), kcal_record("off:2", "off", 260.0, 2026),  # 1 year apart
    ])
    merge("fdc:1", "off:1")
    merge("fdc:2", "off:2")
    for build in (False, True):
        if build:
            build_on(monkeypatch, "2026-10-01")
        assert served("fdc:1", "off") == (260, "off")
        assert served("fdc:2", "off") == (229, "fdc")  # within the window, rank wins
        assert served("fdc:1") == (229, "fdc")  # the core scope has no crowd value


def test_sources_that_agree_outvote_a_lone_outlier_of_higher_rank(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [
        kcal_record("label:1", "label", 300.0, 2026),
        kcal_record("fdc:1", "fdc", 229.0, 2026),
        kcal_record("off:1", "off", 233.0, 2026),  # within 5% of fdc:1
        kcal_record("fdc:2", "fdc", 229.0, 2026),
        kcal_record("off:2", "off", 300.0, 2026),
        kcal_record("off:3", "off", 301.0, 2026),  # two records of one source are one vote
    ])
    merge("label:1", "fdc:1", "off:1")
    merge("fdc:2", "off:2", "off:3")
    for build in (False, True):
        if build:
            build_on(monkeypatch, "2026-10-01")
        assert served("fdc:1", "off") == (229, "fdc")  # fdc and off agree; the label read is alone
        assert served("fdc:1") == (300, "label")  # core only: no agreement, rank wins
        assert served("fdc:2", "off") == (229, "fdc")


def test_agreement_counts_only_values_of_the_same_nutrient_code(monkeypatch):
    from fooddb import ingest

    def carbs(id, source, code, value):
        return rec(id=id, source=source, layer="off" if source == "off" else "core",
                   licence="ODbL-1.0" if source == "off" else "CC0-1.0", values={code: value})

    ingest.run("t", "r1", [
        carbs("label:1", "label", "CHOCDF", 20.0),
        carbs("fdc:1", "fdc", "CHOCDF", 14.9),
        carbs("off:1", "off", "CHOAVL", 14.9),  # same number, other quantity: no vote for fdc:1
    ])
    merge("label:1", "fdc:1", "off:1")
    for build in (False, True):
        if build:
            build_on(monkeypatch, "2026-10-01")
        per_100 = product("fdc:1", "off")["per_100"]
        assert (per_100["CHOCDF"]["value"], per_100["CHOCDF"]["source"]) == (20, "label")
        assert (per_100["CHOAVL"]["value"], per_100["CHOAVL"]["source"]) == (14.9, "off")


def test_an_off_delta_files_label_carbohydrate_under_its_market_code(tmp_path):
    import gzip
    import json

    from fooddb.fetchers import off

    def load(ref, modified, countries):
        path = tmp_path / f"{ref}.jsonl.gz"
        with gzip.open(path, "wt") as f:
            f.write(json.dumps({"code": "4006381333931", "product_name": "Hummus", "last_modified_t": modified,
                                "countries_tags": countries, "nutriments": {
                                    "energy-kj_100g": 958, "carbohydrates_100g": 9.0, "fiber_100g": 6.0}}))
        off.load(path, fetcher="off-test", ref=ref)
        return product("off:04006381333931", "off")["per_100"]

    per_100 = load("d1", 1790000000, ["en:germany"])
    assert per_100["CHOAVL"]["value"] == 9 and "CHOCDF" not in per_100
    assert (per_100["ENERC_KJ"]["value"], per_100["ENERC_KJ"]["unit"]) == (958, "kJ")
    assert round(per_100["ENERC_KCAL"]["value"]) == 229
    per_100 = load("d2", 1790000100, ["en:united-states"])  # a newer edit moves it to the US market
    assert per_100["CHOCDF"]["value"] == 9 and "CHOAVL" not in per_100  # the old code is withdrawn


def test_a_merge_after_a_snapshot_picks_across_the_merged_values_by_the_same_rule(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [kcal_record("fdc:1", "fdc", 229.0, 2018), kcal_record("off:1", "off", 260.0, 2026)])
    build_on(monkeypatch, "2026-10-01")
    assert served("fdc:1", "off") == (229, "fdc")  # separate products at build time
    merge("fdc:1", "off:1")
    assert served("fdc:1", "off") == served("off:1", "off") == (260, "off")
