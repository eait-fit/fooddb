"""Ingest → resolver → API against a real Postgres. Runs only under `./dev test`, which points
FOODDB__BACKEND__DATABASE_URL at this worktree's __test database; skipped otherwise, loudly."""

import os
import re
from datetime import UTC, datetime

import pytest

TEST_URL = os.environ.get("FOODDB_TEST_DATABASE_URL")
os.environ.setdefault("FOODDB__BACKEND__SECRET_KEY", "test-only-secret")  # before fooddb.api mounts the admin
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
        conn.execute(text("truncate food, observation, fetch_run, product, snapshot, snapshot_value, fetcher_check, merge_log, cannot_link, api_key, rate_limit, account, purchase, login_token, usage_month, request_log, admin_action restart identity cascade"))


def client(key: str | None = None):
    from fastapi.testclient import TestClient

    from fooddb.api import app

    return TestClient(app, headers={"Authorization": f"Bearer {key}"} if key else {})


def key(*scopes: str, name: str | None = None, **kw) -> str:
    from fooddb import auth

    return auth.create(name or f"test-{'-'.join(scopes)}", list(scopes), **kw)


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


def observation_count() -> int:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return conn.execute(text("select count(*) from observation")).scalar_one()


def test_a_field_dropped_when_the_record_is_seen_again_at_the_same_time_is_withdrawn():
    from fooddb import ingest

    ingest.run("t", "v1", [rec(values={"ENERC_KCAL": 229.0, "NA": 438.0})])
    assert ingest.run("t", "v2", [rec(values={"ENERC_KCAL": 229.0})]) == (1, 1)  # same observed_at: the withdrawal
    assert "NA" not in product("fdc:1")["per_100"] and product("fdc:1")["per_100"]["ENERC_KCAL"]["value"] == 229
    stored = observation_count()
    assert ingest.run("t", "v3", [rec(values={"ENERC_KCAL": 229.0})]) == (1, 0)  # unchanged: nothing stored
    assert ingest.run("t", "v4", [rec(values={"ENERC_KCAL": 229.0, "NA": 438.0})]) == (1, 1)  # and it can come back
    assert observation_count() == stored + 1 and product("fdc:1")["per_100"]["NA"]["value"] == 438


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
    assert p["serving_g"] == {"value": 90.0} | off
    assert {f: p[f] for f in FIELDS if f != "serving_g"} == {
        "name": {"value": "Pomme Pêche"} | off, "brand": None, "lang": {"value": "fr"} | off,
        "serving_text": {"value": "1 gourde"} | off, "flags": {"value": ["off-flag"]} | off}
    assert p["gtin14"] == [{"value": "03256220000017"} | off]


def test_every_served_number_is_a_json_number_in_rest_and_export(monkeypatch):
    import json

    from fooddb import ingest

    ingest.run("t", "r1", [rec(id="off:03256220000017", source="off", layer="off", licence="ODbL-1.0",
                               gtin14="03256220000017", name="Pomme Pêche", serving_g=90.0,
                               values={"ENERC_KCAL": 45.0, "FIBTG": 1.5})])

    def numbers(p):
        return [p["serving_g"]["value"], *(v["value"] for v in p["per_100"].values())]

    served = product("off:03256220000017", "off")
    assert len(numbers(served)) == 3 and all(type(n) is float for n in numbers(served))
    build_on(monkeypatch, "2026-10-01")
    r = client().get("/v1/snapshots/2026-10-01/export", params={"include": "off"})
    [exported] = map(json.loads, r.text.splitlines())
    assert numbers(exported) == numbers(served) and all(type(n) is float for n in numbers(exported))


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


def test_seals_are_served_with_the_strictest_licence_of_their_inputs_in_rest_and_export(monkeypatch):
    import json

    from fooddb import ingest

    code = acme_hummus_in_both_layers()
    ingest.run("t", "r2", [rec(id="off:" + code, source="off", layer="off", licence="ODbL-1.0", gtin14=code,
                               name="Hummus Classic", brand="Acme", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
                               values=HUMMUS | {"ENERC_KCAL": 240.0, "FIBTG": 6.0, "SUGAR": 1.0})])
    computed = {"source": "fooddb", "record": None}
    core = product("fdc:9")
    assert core["seals"] == {"value": {"CL": {"calories": False}, "MX": {"calories": False}},
                             "licence": "CC0-1.0"} | computed
    full = product("fdc:9", "off")
    assert full["seals"] == {"value": {"CL": {"calories": False, "sugars": False}, "PE": {"sugars": False},
                                       "MX": {"calories": False, "sugars": False}},
                             "licence": "ODbL-1.0"} | computed  # SUGAR comes from the OFF record only

    build_on(monkeypatch, "2026-10-01")
    for include, expected in ((None, core["seals"]), ("off", full["seals"])):
        r = client().get("/v1/snapshots/2026-10-01/export", params={"include": include} if include else {})
        [exported] = [p for p in map(json.loads, r.text.splitlines()) if "fdc:9" in p["records"]]
        assert exported["seals"] == expected == product("fdc:9", include)["seals"]


def test_a_stated_seal_the_values_contradict_holds_those_values_for_review():
    from fooddb import ingest, review

    code = "05449000000996"
    ingest.run("t", "r1", [rec(id="off:" + code, source="off", layer="off", licence="ODbL-1.0", gtin14=code,
                               name="Cola", basis="100ml", categories=["en:beverages", "en:sodas"],
                               labels=["es:exceso-sodio"], values={"ENERC_KCAL": 42.0, "SUGAR": 10.6, "NA": 10.0})])
    [item] = review.queue()
    assert item["checks"] == ["seal-disagreement"]
    assert {v["nutrient"] for v in item["pending"]} == {"NA", "ENERC_KCAL"}  # 10 mg is under 1 mg per kcal
    p = product("off:" + code, "off")
    assert p["category"] == {"value": "beverages", "source": "off", "licence": "ODbL-1.0", "record": "off:" + code}
    assert set(p["per_100"]) == {"SUGAR"}
    assert p["seals"]["value"] == {"CL": {"sugars": True}, "PE": {"sugars": True}}


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
    assert report["fetchers"]["ciqual"]["fresh"] is False and "fdc-branded" not in report["fetchers"]
    assert report["fetchers"]["tfda"]["max_age_hours"] == 192
    assert report["fetchers"]["cofid"]["max_age_hours"] == 192
    assert report["fetchers"]["frida"]["max_age_hours"] == 192
    assert report["fetchers"]["mext"]["max_age_hours"] == 192
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

    def unschedule(self, *args, **kwargs):
        pass

    def upsert(self, fn, *, client_id, priority=50, max_runtime_seconds=None, **kwargs):  # 50 = Priority.NORMAL
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
    for name, table in jobs.TABLES.items():
        monkeypatch.setattr(table, "fetch", lambda force=False, name=name: ingest.run(
            name, "r1", [rec(id=f"{name}:1", source=name)]))
    deltas = iter(["d1", "d2"])

    def off_fetch(max_files=1):
        name = next(deltas)
        foods, obs = ingest.run(off.FETCHER, name, [rec(
            id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0", gtin14="04006381333931",
            name="Chocolate hazelnut spread", values={"ENERC_KCAL": 539.0 if name == "d1" else 540.0})])
        return [(name, foods, obs)]

    monkeypatch.setattr(off, "fetch", off_fetch)

    jobs.schedule()
    # FDC Branded and Fineli are off by default; CIQUAL, CoFID, Frida, Matvaretabellen, MEXT and TFDA fill a fresh install.
    assert q.drain() == ["fetch_fdc", "fetch_fdc", "fetch_table", "fetch_table", "fetch_table", "fetch_table",
                         "fetch_table", "fetch_table", "match_products", "build_snapshot"]
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


def test_a_wine_with_its_alcohol_is_served_and_a_mislabelled_one_waits_for_review():
    from fooddb import ingest, review

    wine = {"ENERC_KCAL": 70, "PROCNT": 0.1, "FAT": 0, "CHOCDF": 2.6, "ALC": 9.5}
    ingest.run("t", "wines", [rec(id="frida:164", source="frida", values=wine, categories=["frida:112"]),
                               rec(id="frida:165", source="frida", values=wine | {"ENERC_KCAL": 400})])
    assert review.queue()[0]["record"] == "frida:165" and len(review.queue()) == 1
    assert {v["nutrient"] for v in review.queue()[0]["pending"]} == {"ENERC_KCAL", "PROCNT", "FAT", "CHOCDF", "ALC"}
    served = product("frida:164")["per_100"]
    assert (served["ALC"]["value"], served["ENERC_KCAL"]["value"]) == (9.5, 70)


def test_an_accepted_value_is_served_from_the_next_snapshot(monkeypatch):
    from fooddb import review

    ingest_typo()
    build_on(monkeypatch, "2026-10-01")
    obs = pending_id("ENERC_KCAL")
    r = client(key("review")).post(f"/v1/review/{obs}", json={"decision": "accept", "by": "tester", "note": "label says so"})
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
    c = client(key("review"))
    assert c.post(f"/v1/review/{obs}", json={"decision": "reject", "by": "tester"}).json()["status"] == "rejected"
    # The source sends the same typo again: it is not stored again, so it does not come back for review.
    ingest.run("t", "typo-again", [rec(observed_at=datetime(2026, 7, 1, tzinfo=UTC), values=TYPO)])
    build_on(monkeypatch, "2026-10-01")
    assert kcal("fdc:1") == 229
    assert c.get("/v1/review").json()["items"][0]["pending"][0]["nutrient"] == "SUGAR"


def test_review_decisions_are_final_and_validated():
    ingest_typo()
    obs = pending_id("ENERC_KCAL")
    c = client(key("review"))
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
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="kirill")},
                  follow_redirects=False).status_code == 302
    page = c.get("/admin/observation/list")
    assert page.status_code == 200 and "2290" in page.text and "FIBTG" not in page.text
    assert c.get(f"/admin/observation/action/accept?pks={obs}", follow_redirects=False).status_code == 302
    with engine().connect() as conn:
        row = conn.execute(text("select status, reviewed_by from observation where id = :id"), {"id": obs}).one()
    assert tuple(row) == ("accepted", "kirill")


BISCUITS = {"PROCNT": 7.8, "CHOAVL": 76.0, "FAT": 11.0, "FIBTG": 2.0, "ENERC_KCAL": 700.8, "ENERC_KJ": 1847.6,
            "SUGAR": 23.0, "FASAT": 1.7, "NA": 15.6}


def ingest_biscuits(**kw) -> None:
    from fooddb import ingest

    code = "08002330009380"
    ingest.run("t", "off", [rec(id=f"off:{code}", source="off", layer="off", licence="ODbL-1.0", gtin14=code,
                                name="Biscotti Petit", brand="Esselunga", values=BISCUITS, **kw)])


def admin_client():
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="kirill")},
                  follow_redirects=False).status_code == 302
    return c


def test_the_review_page_explains_an_energy_mismatch_with_the_numbers_and_shows_accepted_values():
    ingest_biscuits()
    page = admin_client().get("/admin/review")
    assert page.status_code == 200, page.text
    text = page.text
    assert "Biscotti Petit" in text and "Esselunga" in text and "off:08002330009380" in text
    assert "https://world.openfoodfacts.org/product/8002330009380" in text and 'target="_blank"' in text
    assert "macros give 438 kcal by Atwater" in text and "declared 700.8 kcal" in text and "kJ/4.184 gives 442 kcal" in text
    for nutrient in ("ENERC_KJ", "SUGAR", "FASAT", "NA"):  # accepted values sit next to the pending ones
        assert re.search(rf"<td>{nutrient}</td>.*?accepted", text, re.S), nutrient
    assert text.count("Accept all pending") == 1 and "pks=" in text
    assert "ENERC_KCAL" in text and ">pending<" in text


def test_atwater_is_one_function_for_the_check_and_its_explanation():
    from fooddb import checks

    assert round(checks.atwater(BISCUITS)) == 438
    assert checks.atwater({"PROCNT": 1.0}) is None
    assert "ENERC_KCAL" in checks.flags(BISCUITS)["energy-mismatch"]
    assert checks.explain("sugars-over-carbs", {"SUGAR": 12.0, "CHOCDF": 10.0}) == "sugars 12 g are over carbohydrate 10 g"
    assert checks.explain("negative-value", {}, {"FAT", "NA"}) == "implicates FAT, NA"


def test_the_review_page_filters_by_check_and_source_and_pages(monkeypatch):
    from fooddb import ingest, review

    ingest_biscuits()
    ingest.run("t", "fdc", [rec(id="fdc:7", values={"ENERC_KCAL": 229.0, "SUGAR": 20.0, "CHOCDF": 9.0})])
    facets = review.facets()
    assert facets["total"] == 2 and facets["checks"] == {"energy-mismatch": 1, "sugars-over-carbs": 1}
    assert facets["sources"] == {"fdc": 1, "off": 1}
    assert review.facets(check="energy-mismatch")["sources"] == {"off": 1}
    c = admin_client()
    both = c.get("/admin/review").text
    assert "Biscotti Petit" in both and "Hummus, commercial" in both
    only = c.get("/admin/review", params={"check": "sugars-over-carbs"}).text
    assert "Hummus, commercial" in only and "Biscotti Petit" not in only
    assert "energy-mismatch (1)" in only and "sugars-over-carbs (1)" in only
    only = c.get("/admin/review", params={"source": "off"}).text
    assert "Biscotti Petit" in only and "Hummus, commercial" not in only
    assert "Biscotti Petit" not in c.get("/admin/review", params={"check": "sugars-over-carbs", "source": "off"}).text
    monkeypatch.setattr("fooddb.admin.PAGE_SIZE", 1)
    first = c.get("/admin/review").text
    assert "Records 1–1 of 2" in first and "?offset=1" in first and "Previous" not in first
    second = c.get("/admin/review", params={"offset": 1}).text
    assert "Records 2–2 of 2" in second and "Previous" in second and "Next" not in second
    assert ("Biscotti Petit" in first) != ("Biscotti Petit" in second)
    assert c.get("/admin/review", params={"offset": "junk", "check": "nope"}).status_code == 200


def test_a_decision_from_the_review_page_returns_to_it_and_refuses_an_unsafe_next():
    from urllib.parse import quote

    from fooddb import review

    ingest_biscuits()
    c = admin_client()
    pks = [v["observation_id"] for v in review.queue()[0]["pending"]]
    back = "/admin/review?check=energy-mismatch&offset=0"
    assert "&next=" + quote(back, safe="/") in c.get(back).text
    r = c.get(f"/admin/observation/action/reject?pks={pks[0]}&next={quote(back, safe='')}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == back
    r = c.get(f"/admin/observation/action/accept?pks={','.join(map(str, pks[1:]))}&next={quote(back, safe='')}",
              follow_redirects=False)
    assert r.headers["location"] == back and review.queue() == []
    for bad in ("https://evil.example/admin/review", "//evil.example/admin/review", "/elsewhere", "/admin/../v1/review",
                "/administrator", "\\\\evil.example", "javascript:alert(1)", ""):
        r = c.get(f"/admin/observation/action/accept?pks=0&next={quote(bad, safe='')}", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].endswith("/admin/observation/list"), bad


def test_the_queue_is_unchanged_for_callers_that_ask_for_nothing_new():
    from fooddb import review

    ingest_typo()
    [item] = review.queue()
    assert set(item) == {"record", "product_id", "layer", "name", "source", "photo", "checks", "pending", "served"}
    assert set(item["pending"][0]) == {"observation_id", "nutrient", "unit", "basis", "value", "observed_at"}
    assert review.queue(100, ("%",)) == review.queue() == review.queue(100, ("fdc:%",)) != review.queue(offset=1)
    [detailed] = review.queue(detail=True)
    assert {k: v for k, v in detailed.items() if k not in ("brand", "category", "images", "values", "why")} == item
    assert {(v["nutrient"], v["status"]) for v in detailed["values"]} >= {("ENERC_KCAL", "pending"), ("FIBTG", "accepted")}
    assert "macros give" in detailed["why"]["energy-mismatch"] and "2290" in detailed["why"]["energy-mismatch"]


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


def test_a_reload_of_an_unedited_off_product_serves_only_the_new_carbohydrate_code(tmp_path):
    import gzip
    import json

    from fooddb.fetchers import off

    def load(ref, countries):
        path = tmp_path / f"{ref}.jsonl.gz"
        with gzip.open(path, "wt") as f:
            f.write(json.dumps({"code": "4006381333931", "product_name": "Hummus", "last_modified_t": 1790000000,
                                "countries_tags": countries, "nutriments": {"carbohydrates_100g": 9.0}}))
        off.load(path, fetcher="off-test", ref=ref)
        return product("off:04006381333931", "off")["per_100"]

    assert load("old-parser", ["en:united-states"]).keys() == {"CHOCDF"}
    assert load("new-parser", ["en:germany"]).keys() == {"CHOAVL"}  # same last_modified_t: the old code is withdrawn


def test_a_merge_after_a_snapshot_picks_across_the_merged_values_by_the_same_rule(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [kcal_record("fdc:1", "fdc", 229.0, 2018), kcal_record("off:1", "off", 260.0, 2026)])
    build_on(monkeypatch, "2026-10-01")
    assert served("fdc:1", "off") == (229, "fdc")  # separate products at build time
    merge("fdc:1", "off:1")
    assert served("fdc:1", "off") == served("off:1", "off") == (260, "off")


def label_record(id: str, value: float, month: int, approved: bool = False):
    r = rec(id=id, source="label", licence="LicenseRef-fooddb",
            observed_at=datetime(2026, month, 1, tzinfo=UTC), values={"ENERC_KCAL": value})
    return r, approved


def ingest_labels(*labels) -> None:
    """Ingest label reads (accepted by the checks); an approved one also carries a reviewer."""
    from sqlalchemy import text

    from fooddb import ingest
    from fooddb.db import engine

    ingest.run("t", "labels", [r for r, _ in labels])
    with engine().begin() as conn:
        for r, approved in labels:
            if approved:
                conn.execute(text("update observation set reviewed_by = 'tester', reviewed_at = now() where food_id = :f"),
                             {"f": r.id})


def agreeing_tables(*ids: str) -> list:
    return [kcal_record(i, s, 229.0, y) for i, s, y in zip(ids, ("fdc", "ciqual"), (2026, 2025), strict=True)]


def test_an_approved_label_read_beats_two_agreeing_sources(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", agreeing_tables("fdc:1", "ciqual:1"))
    ingest_labels(label_record("label:aa", 260.0, 1, True))
    merge("fdc:1", "ciqual:1", "label:aa")
    assert served("fdc:1") == (260, "label")


def test_an_auto_accepted_label_read_gets_no_override():
    from fooddb import ingest

    ingest.run("t", "r1", agreeing_tables("fdc:1", "ciqual:1"))
    ingest_labels(label_record("label:aa", 260.0, 1))
    merge("fdc:1", "ciqual:1", "label:aa")
    assert served("fdc:1") == (229, "fdc")  # agreement still outvotes a lone label read


def test_a_rejected_or_pending_label_read_never_wins():
    from sqlalchemy import text

    from fooddb import ingest
    from fooddb.db import engine

    ingest.run("t", "r1", agreeing_tables("fdc:1", "ciqual:1"))
    ingest_labels(label_record("label:aa", 260.0, 1), label_record("label:bb", 270.0, 2))
    with engine().begin() as conn:
        conn.execute(text("update observation set status = 'rejected', reviewed_by = 'tester' where food_id = 'label:aa'"))
        conn.execute(text("update observation set status = 'pending', reviewed_by = 'tester' where food_id = 'label:bb'"))
    merge("fdc:1", "ciqual:1", "label:aa", "label:bb")
    assert served("fdc:1") == (229, "fdc")


def test_the_newest_of_several_approved_label_reads_wins():
    from fooddb import ingest

    ingest.run("t", "r1", agreeing_tables("fdc:1", "ciqual:1"))
    ingest_labels(label_record("label:aa", 250.0, 3, True), label_record("label:bb", 260.0, 5, True),
                  label_record("label:cc", 270.0, 4, True))
    merge("fdc:1", "ciqual:1", "label:aa", "label:bb", "label:cc")
    assert served("fdc:1") == (260, "label")


def test_an_approved_label_read_wins_in_the_snapshot_and_after_a_merge(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", agreeing_tables("fdc:1", "ciqual:1"))
    ingest_labels(label_record("label:aa", 260.0, 1, True))
    merge("fdc:1", "ciqual:1")
    build_on(monkeypatch, "2026-10-01")
    assert served("fdc:1") == (229, "fdc")  # the label record is a separate product here
    merge("fdc:1", "label:aa")
    assert served("fdc:1") == served("label:aa") == (260, "label")  # merge-follow keeps the override
    build_on(monkeypatch, "2026-10-02")
    assert served("fdc:1") == (260, "label")


def log_rows(kind: str) -> list[dict]:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text("select * from merge_log where kind = :k order by id"),
                                              {"k": kind}).mappings()]


MERGED_HUMMUS = HUMMUS | {"ENERC_KCAL": 233.0, "FIBTG": 6.0}


def wrongly_merged_hummus() -> tuple[int, int]:
    """Two hummus records that matching merges; the test then calls the merge wrong."""
    from fooddb import ingest, jobs

    ingest.run("t", "r1", [
        rec(id="fdc:1", name="Hummus, commercial", values=HUMMUS),
        rec(id="fdc:2", name="Hummus, commercial", observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=MERGED_HUMMUS),
    ])
    survivor, merged_away = product("fdc:1")["id"], product("fdc:2")["id"]
    jobs.match_products()
    assert product("fdc:2")["id"] == survivor
    return survivor, merged_away


def split(pid: int, food_ids: list[str], **body):
    import uuid

    reviewer = client(key("review", name=f"reviewer-{uuid.uuid4().hex[:8]}"))
    return reviewer.post(f"/v1/products/{pid}/split", json={"food_ids": food_ids, "by": "tester"} | body)


def test_matching_logs_each_merge_with_its_probability_and_the_records_it_moved():
    survivor, merged_away = wrongly_merged_hummus()
    [row] = log_rows("merge")
    assert (row["from_product"], row["into_product"], row["food_ids"]) == (merged_away, survivor, ["fdc:2"])
    assert row["threshold"] == 0.95 and 0.95 <= row["probability"] <= 1


def test_a_split_undoes_a_wrong_merge_and_matching_never_joins_the_records_again():
    from fooddb import jobs

    survivor, merged_away = wrongly_merged_hummus()
    r = split(survivor, ["fdc:2"], note="two recipes")
    assert r.status_code == 200, r.text
    assert (r.json()["split_into"], r.json()["restored"]) == (merged_away, True)
    # The merged-away id is its own product again, so old links to it work again.
    assert client().get(f"/v1/foods/{merged_away}").json()["records"] == ["fdc:2"]
    assert client().get(f"/v1/foods/{survivor}").json()["records"] == ["fdc:1"]
    [row] = log_rows("split")
    assert (row["from_product"], row["into_product"], row["food_ids"], row["by"], row["note"]) == (
        survivor, merged_away, ["fdc:2"], "tester", "two recipes")
    jobs.match_products()
    assert product("fdc:1")["id"] == survivor and product("fdc:2")["id"] == merged_away
    assert len(log_rows("merge")) == 1


def test_a_split_without_a_logged_merge_makes_a_new_product():
    from fooddb import ingest

    ingest.run("t", "r1", [rec(id="fdc:1"), rec(id="fdc:2"), rec(id="fdc:3")])
    merge("fdc:1", "fdc:2", "fdc:3")  # merged before the log existed
    r = split(product("fdc:1")["id"], ["fdc:2", "fdc:3"])
    assert r.status_code == 200, r.text
    assert r.json()["split_into"] > 3 and not r.json()["restored"]
    p = product("fdc:3")
    assert (p["id"], sorted(p["records"])) == (r.json()["split_into"], ["fdc:2", "fdc:3"])


def test_a_split_is_validated():
    survivor, merged_away = wrongly_merged_hummus()
    assert split(999999, ["fdc:2"]).status_code == 404
    assert split(merged_away, ["fdc:2"]).status_code == 409  # split the product it answers as
    assert split(survivor, ["fdc:3"]).status_code == 422  # not a record of this product
    assert split(survivor, ["fdc:1", "fdc:2"]).status_code == 422  # a split leaves at least one record
    assert split(survivor, []).status_code == 422
    assert split(survivor, ["fdc:2"], by="").status_code == 422  # who decided is required


def test_matching_never_puts_a_cannot_link_pair_in_one_product():
    from sqlalchemy import text

    from fooddb import ingest, jobs
    from fooddb.db import engine

    ingest.run("t", "r1", [rec(id=f"fdc:{i}", name="Hummus, commercial", values=HUMMUS) for i in (1, 2, 3)])
    with engine().begin() as conn:
        conn.execute(text("insert into cannot_link (food_a, food_b, by) values ('fdc:1', 'fdc:3', 'tester')"))
    jobs.match_products()
    assert product("fdc:1")["id"] != product("fdc:3")["id"]
    assert product("fdc:2")["id"] in (product("fdc:1")["id"], product("fdc:3")["id"])


def test_a_split_keeps_a_past_days_values_and_todays_follow_the_next_build(monkeypatch):
    survivor, merged_away = wrongly_merged_hummus()
    build_on(monkeypatch, "2026-10-01")

    def values(pid, **params):
        return {n: v["value"] for n, v in client().get(f"/v1/foods/{pid}", params=params).json()["per_100"].items()}

    assert values(survivor) == MERGED_HUMMUS
    assert split(survivor, ["fdc:2"]).status_code == 200
    assert values(survivor, snapshot="2026-10-01") == MERGED_HUMMUS  # 2026-10-01 is over: it keeps its values
    build_on(monkeypatch, "2026-10-02")
    assert values(survivor) == HUMMUS and values(merged_away) == MERGED_HUMMUS
    assert values(survivor, snapshot="2026-10-01") == MERGED_HUMMUS


def test_mcp_agents_split_like_the_api():
    survivor, merged_away = wrongly_merged_hummus()
    assert call("split_product", product_id=survivor, food_ids=["fdc:9"], by="agent").is_error
    out = call("split_product", product_id=survivor, food_ids=["fdc:2"], by="agent").structured_content
    assert out["split_into"] == merged_away


def test_admin_lists_the_merge_log_and_splits_a_merge():
    survivor, merged_away = wrongly_merged_hummus()
    [row] = log_rows("merge")
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="kirill")},
                  follow_redirects=False).status_code == 302
    page = c.get("/admin/merge-log/list")
    assert page.status_code == 200 and "fdc:2" in page.text
    assert c.get(f"/admin/merge-log/action/split?pks={row['id']}", follow_redirects=False).status_code == 302
    assert product("fdc:2")["id"] == merged_away
    assert log_rows("split")[0]["by"] == "kirill"


def test_match_train_saves_a_model_that_matching_then_uses(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from fooddb import ingest, jobs
    from fooddb.cli import app

    beans = {"ENERC_KCAL": 31.0, "PROCNT": 1.8, "FAT": 0.2, "CHOCDF": 7.0}
    ingest.run("t", "r1", [
        rec(id="fdc:1", name="Hummus, commercial", values=HUMMUS),
        rec(id="fdc:2", name="Hummus, commercial", values=HUMMUS | {"ENERC_KCAL": 233.0}),
        rec(id="fdc:3", name="Beans, snap, green, raw", values=beans),
        rec(id="fdc:4", name="Beans, snap, yellow, raw", values=beans),
        rec(id="fdc:9", gtin14="04006381333931", name="ACME, HUMMUS CLASSIC", brand="Acme", values=HUMMUS),
        rec(id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0", gtin14="04006381333931",
            name="Hummus Classic", brand="Acme", values=HUMMUS | {"ENERC_KCAL": 240.0}),
    ])
    path = tmp_path / "model.json"
    monkeypatch.setenv("FOODDB__BACKEND__MATCH_MODEL", str(path))
    r = CliRunner().invoke(app, ["match", "train"])
    assert r.exit_code == 0, r.output
    model = json.loads(path.read_text())
    assert {c["output_column_name"] for c in model["comparisons"]} == {"gtin14", "name_words", "brand", "nutrients"}
    # Matching reads the saved model: one that calls every pair unlikely merges nothing.
    model["probability_two_random_records_match"] = 1e-12
    path.write_text(json.dumps(model))
    jobs.match_products()
    assert product("fdc:1")["id"] != product("fdc:2")["id"]
    monkeypatch.setenv("FOODDB__BACKEND__MATCH_MODEL", str(tmp_path / "absent.json"))  # no model yet: hand-set weights
    jobs.match_products()
    assert product("fdc:1")["id"] == product("fdc:2")["id"]


def test_a_national_table_is_served_with_its_licence_and_attribution():
    from pathlib import Path

    from fooddb import ingest
    from fooddb.fetchers import ciqual

    xlsx = Path(__file__).parent / "fixtures" / "ciqual.xlsx"
    assert ingest.run(ciqual.FETCHER, "t", ciqual.records(xlsx, datetime(2025, 11, 3, tzinfo=UTC)))[0] == 3
    p = product("ciqual:24999")
    assert p["name"] == {"value": "Dessert (average)", "source": "ciqual", "licence": "etalab-2.0",
                         "record": "ciqual:24999"}
    assert (p["per_100"]["CHOAVL"]["value"], p["per_100"]["CHOAVL"]["licence"]) == (32.9, "etalab-2.0")
    assert p["attribution"] == [{"source": "ciqual", "licence": "etalab-2.0", "text": ciqual.ATTRIBUTION}]
    assert product("ciqual:25600")["seals"]["licence"] == "etalab-2.0"


def test_tfda_is_served_in_chinese_with_its_licence_and_attribution_and_outranks_the_crowd():
    from pathlib import Path

    from fooddb import ingest
    from fooddb.fetchers import tfda

    zipped = Path(__file__).parent / "fixtures" / "tfda.zip"
    assert ingest.run(tfda.FETCHER, "t", tfda.records(zipped, datetime(2026, 10, 5, tzinfo=UTC)))[0] == 5
    p = product("tfda:D3200404")
    assert p["name"] == {"value": "富士蘋果", "source": "tfda", "licence": "OGDL-Taiwan-1.0", "record": "tfda:D3200404"}
    assert p["lang"]["value"] == "zh-TW"
    assert (p["per_100"]["SUGAR"]["value"], p["per_100"]["SUGAR"]["licence"]) == (10.4, "OGDL-Taiwan-1.0")
    assert p["per_100"]["CHOCDF"]["value"] == 13.1 and "CHOAVL" not in p["per_100"]
    assert p["attribution"] == [{"source": "tfda", "licence": "OGDL-Taiwan-1.0", "text": tfda.ATTRIBUTION}]
    ingest.run("t", "r2", [kcal_record("tfda:1", "tfda", 229.0, 2026), kcal_record("off:1", "off", 260.0, 2026)])
    merge("tfda:1", "off:1")
    assert served("off:1", "off") == (229, "tfda")


def test_cofid_is_served_with_its_licence_and_attribution_and_outranks_the_crowd():
    from pathlib import Path

    from fooddb import ingest
    from fooddb.fetchers import cofid

    xlsx = Path(__file__).parent / "fixtures" / "cofid.xlsx"
    assert ingest.run(cofid.FETCHER, "t", cofid.records(xlsx, datetime(2021, 3, 19, tzinfo=UTC)))[0] == 5
    p = product("cofid:14-319")
    assert p["name"] == {"value": "Apples, eating, raw, flesh and skin", "source": "cofid", "licence": "OGL-UK-3.0",
                         "record": "cofid:14-319"}
    assert (p["per_100"]["FIBTG"]["value"], p["per_100"]["FIBTG"]["licence"]) == (1.2, "OGL-UK-3.0")
    assert "CHOAVL" not in p["per_100"] and "CHOCDF" not in p["per_100"]
    assert p["attribution"] == [{"source": "cofid", "licence": "OGL-UK-3.0", "text": cofid.ATTRIBUTION}]
    ingest.run("t", "r2", [kcal_record("cofid:1", "cofid", 229.0, 2021), kcal_record("off:1", "off", 260.0, 2022)])
    merge("cofid:1", "off:1")
    assert served("off:1", "off") == (229, "cofid")


def test_frida_is_served_with_both_carbohydrate_codes_and_outranks_the_crowd():
    from pathlib import Path

    from fooddb import ingest
    from fooddb.fetchers import frida

    xlsx = Path(__file__).parent / "fixtures" / "frida.xlsx"
    assert ingest.run(frida.FETCHER, "t", frida.records(xlsx, datetime(2026, 1, 19, tzinfo=UTC)))[0] == 4
    p = product("frida:1")
    assert p["name"] == {"value": "Strawberry, raw", "source": "frida", "licence": "CC-BY-4.0", "record": "frida:1"}
    assert (p["per_100"]["CHOAVL"]["licence"], p["per_100"]["CHOCDF"]["source"]) == ("CC-BY-4.0", "frida")
    assert p["per_100"]["CHOCDF"]["value"] > p["per_100"]["CHOAVL"]["value"]
    assert p["attribution"] == [{"source": "frida", "licence": "CC-BY-4.0", "text": frida.ATTRIBUTION}]
    ingest.run("t", "r2", [kcal_record("frida:2", "frida", 229.0, 2025), kcal_record("off:1", "off", 260.0, 2026)])
    merge("frida:2", "off:1")
    assert served("off:1", "off") == (229, "frida")


def test_mext_is_served_in_japanese_with_both_carbohydrate_codes_and_its_attribution():
    from pathlib import Path

    from fooddb import ingest, review
    from fooddb.fetchers import mext

    fixtures = Path(__file__).parent / "fixtures"
    records = mext.records(fixtures / "mext.xlsx", datetime(2026, 3, 27, tzinfo=UTC),
                           fixtures / "mext_fatty_acids.xlsx", fixtures / "mext_carbohydrates.xlsx")
    assert ingest.run(mext.FETCHER, "t", records)[0] == 10
    p = product("mext:07107")
    assert (p["per_100"]["SUGAR"]["value"], p["per_100"]["SUGAR"]["licence"]) == (15.5, "mext-free-use")
    assert (p["per_100"]["FASAT"]["value"], p["per_100"]["FASAT"]["source"]) == (0.07, "mext")
    assert not [i for i in review.queue() if i["record"] == "mext:07107"]  # no check flags the joined values
    assert p["name"] == {"value": "バナナ 生", "source": "mext", "licence": "mext-free-use", "record": "mext:07107"}
    assert p["lang"]["value"] == "ja"
    assert (p["per_100"]["CHOAVL"]["value"], p["per_100"]["CHOAVL"]["licence"]) == (18.5, "mext-free-use")
    assert p["per_100"]["CHOCDF"]["value"] == 22.5
    assert p["attribution"] == [{"source": "mext", "licence": "mext-free-use", "text": mext.ATTRIBUTION}]
    ingest.run("t", "r2", [kcal_record("mext:1", "mext", 229.0, 2026), kcal_record("off:1", "off", 260.0, 2026)])
    merge("mext:1", "off:1")
    assert served("off:1", "off") == (229, "mext")


def test_national_tables_rank_with_fdc_above_the_crowd(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [
        kcal_record("ciqual:1", "ciqual", 229.0, 2025), kcal_record("off:1", "off", 260.0, 2026),
        kcal_record("fdc:2", "fdc", 200.0, 2026), kcal_record("matvaretabellen:2", "matvaretabellen", 180.0, 2025),
    ])
    merge("ciqual:1", "off:1")
    merge("fdc:2", "matvaretabellen:2")
    for build in (False, True):
        if build:
            build_on(monkeypatch, "2026-10-01")
        assert served("off:1", "off") == (229, "ciqual")  # a table outranks the crowd
        assert served("fdc:2") == (200, "fdc")  # FDC and the national tables share a rank: the newer value wins
    # Attribution lists only the sources of what is served.
    assert [a["source"] for a in product("off:1", "off")["attribution"]] == ["ciqual"]
    assert product("fdc:2")["attribution"] == []


BRAND_GTIN = "04006381333931"


def held_record(**kw):
    return rec(id=f"brand:{BRAND_GTIN}", source="brand", gtin14=BRAND_GTIN, name="Acme Hummus", brand="Acme",
               review_all=True, **kw)


def test_a_record_whose_every_value_waits_for_review_is_not_served_at_all(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [held_record()])
    c = client()
    assert c.get(f"/v1/products/{BRAND_GTIN}").status_code == 404
    assert c.get(f"/v1/records/brand:{BRAND_GTIN}").status_code == 404
    assert c.get("/v1/foods", params={"q": "hummus"}).json()["items"] == []
    assert call("get_product_by_barcode", barcode=BRAND_GTIN).is_error
    pid = _food_product(f"brand:{BRAND_GTIN}")
    assert c.get(f"/v1/foods/{pid}").status_code == 404
    build_on(monkeypatch, "2026-10-01")
    assert c.get("/v1/snapshots/2026-10-01/export").text == ""


def _food_product(record_id: str) -> int:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return conn.execute(text("select product_id from food where id = :i"), {"i": record_id}).scalar_one()


def test_a_held_record_does_not_name_or_tag_the_product_it_is_merged_into(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec(), held_record(values={"ENERC_KCAL": 400.0})])
    merge("fdc:1", f"brand:{BRAND_GTIN}")
    p = product("fdc:1")
    assert p["name"]["value"] == "Hummus, commercial" and p["name"]["source"] == "fdc"
    assert p["brand"] is None and p["gtin14"] == [] and p["records"] == ["fdc:1"]
    assert p["per_100"]["ENERC_KCAL"]["value"] == 229
    assert client().get(f"/v1/products/{BRAND_GTIN}").status_code == 404


def test_accepting_one_value_lets_the_record_name_the_product():
    from fooddb import ingest, review

    ingest.run("t", "r1", [held_record()])
    obs = next(v["observation_id"] for i in review.queue() for v in i["pending"] if v["nutrient"] == "PROCNT")
    review.decide(obs, "accept", "tester")
    p = client().get(f"/v1/products/{BRAND_GTIN}").json()["items"][0]
    assert p["name"]["value"] == "Acme Hummus" and p["name"]["source"] == "brand"
    assert p["gtin14"][0]["value"] == BRAND_GTIN and set(p["per_100"]) == {"PROCNT"}


def test_a_record_with_only_rejected_values_is_not_served():
    from fooddb import ingest, review

    ingest.run("t", "r1", [held_record(values={"PROCNT": 7.4})])
    [item] = review.queue()
    review.decide(item["pending"][0]["observation_id"], "reject", "tester")
    assert client().get(f"/v1/products/{BRAND_GTIN}").status_code == 404
