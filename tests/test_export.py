"""Snapshot export: the bulk read a consumer (eait) syncs its local copy from. Database suite."""

import gzip
import json
from datetime import UTC, date, datetime

from tests.test_db import HUMMUS, build_on, clean, client, pytestmark, rec  # noqa: F401

OFF = dict(id="off:04006381333931", source="off", layer="off", licence="ODbL-1.0", gtin14="04006381333931",
           name="Hummus classic", values={"ENERC_KCAL": 300.0})


def export(day: str, **params) -> list[dict]:
    r = client().get(f"/v1/snapshots/{day}/export", params=params)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in r.text.splitlines()]


def rest(pid: int, day: str, **params) -> dict:
    r = client().get(f"/v1/foods/{pid}", params={"snapshot": day} | params)
    assert r.status_code == 200, r.text
    return r.json()


def test_snapshots_list_newest_first_and_only_past_days_are_final(monkeypatch):
    from fooddb import ingest, snapshot

    ingest.run("t", "r1", [rec(), rec(**OFF)])
    build_on(monkeypatch, "2026-10-01")
    build_on(monkeypatch, "2026-10-02")
    monkeypatch.setattr(snapshot, "today", lambda: date(2026, 10, 2))
    body = client().get("/v1/snapshots").json()
    assert body["today"] == "2026-10-02" and "final" in body["note"]
    assert [(i["day"], i["products"], i["final"]) for i in body["items"]] == [
        ("2026-10-02", 2, False), ("2026-10-01", 2, True)]
    assert all(i["built_at"] for i in body["items"])


def test_export_of_a_pinned_day_has_exactly_that_days_products_and_values(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec()])
    build_on(monkeypatch, "2026-10-01")
    ingest.run("t", "r2", [rec(observed_at=datetime(2026, 6, 1, tzinfo=UTC), values={"ENERC_KCAL": 231.0}),
                           rec(id="fdc:9", name="Lentils, raw", values={"ENERC_KCAL": 352.0})])
    build_on(monkeypatch, "2026-10-02")

    old = export("2026-10-01")
    assert [p["records"] for p in old] == [["fdc:1"]]
    assert old[0]["per_100"]["ENERC_KCAL"]["value"] == 229
    assert old == [rest(old[0]["id"], "2026-10-01")]  # the same shape the REST reads return
    new = export("2026-10-02")
    assert sorted(r for p in new for r in p["records"]) == ["fdc:1", "fdc:9"]
    assert new == [rest(p["id"], "2026-10-02") for p in new]
    assert client().get("/v1/snapshots/2026-09-01/export").status_code == 404


def test_export_after_a_merge_keeps_the_values_the_snapshot_froze(monkeypatch):
    from fooddb import ingest, jobs

    ingest.run("t", "r1", [
        rec(id="fdc:1", name="Hummus, commercial", values=HUMMUS),
        rec(id="fdc:2", name="Hummus, commercial", observed_at=datetime(2026, 6, 1, tzinfo=UTC),
            values=HUMMUS | {"ENERC_KCAL": 233.0, "FIBTG": 6.0}),
    ])
    build_on(monkeypatch, "2026-10-01")
    jobs.match_products()
    [p] = export("2026-10-01")
    assert sorted(p["records"]) == ["fdc:1", "fdc:2"]
    assert {n: v["value"] for n, v in p["per_100"].items()} == HUMMUS | {"ENERC_KCAL": 233.0, "FIBTG": 6.0}


def test_export_keeps_the_off_layer_out_unless_asked(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec(), rec(**OFF)])
    build_on(monkeypatch, "2026-10-01")
    assert [p["records"] for p in export("2026-10-01")] == [["fdc:1"]]
    both = export("2026-10-01", include="off")
    assert sorted(r for p in both for r in p["records"]) == ["fdc:1", "off:04006381333931"]
    licences = {v["licence"] for p in both for v in p["per_100"].values()}
    assert licences == {"CC0-1.0", "ODbL-1.0"}
    assert {(p["name"]["record"], p["name"]["licence"], p["gtin14"][0]["licence"] if p["gtin14"] else None)
            for p in both} == {("fdc:1", "CC0-1.0", None), ("off:04006381333931", "ODbL-1.0", "ODbL-1.0")}
    assert "ODbL" not in client().get("/v1/snapshots/2026-10-01/export").text


def test_export_etag_is_stable_for_a_final_day_and_gzip_on_request(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec()])
    build_on(monkeypatch, "2026-10-01")
    url = "/v1/snapshots/2026-10-01/export"
    first = client().get(url, headers={"Accept-Encoding": "identity"})
    build_on(monkeypatch, "2026-10-02")
    again = client().get(url, headers={"Accept-Encoding": "gzip"})
    assert first.headers["etag"] == again.headers["etag"] and first.headers["last-modified"]
    assert "content-encoding" not in first.headers and again.headers["content-encoding"] == "gzip"
    assert again.text == first.text  # httpx decodes the gzip body
    assert client().get(url, params={"include": "off"}).headers["etag"] != first.headers["etag"]
    unchanged = client().get(url, headers={"If-None-Match": first.headers["etag"]})
    assert unchanged.status_code == 304 and not unchanged.content


def test_export_streams_in_batches(monkeypatch):
    from fooddb import export as ex
    from fooddb import ingest, resolve

    ingest.run("t", "r1", [rec(id=f"fdc:{i}", name=f"Food number {i} {'x' * i}") for i in range(5)])
    build_on(monkeypatch, "2026-10-01")
    calls = []
    real = resolve.products
    monkeypatch.setattr(ex, "BATCH", 2)
    monkeypatch.setattr(resolve, "products", lambda pids, *a, **kw: calls.append(len(pids)) or real(pids, *a, **kw))
    assert len(export("2026-10-01")) == 5
    assert calls == [2, 2, 1]


def test_cli_export_writes_the_same_lines_gzipped(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from fooddb import ingest
    from fooddb.cli import app

    ingest.run("t", "r1", [rec(), rec(**OFF)])
    build_on(monkeypatch, "2026-10-01")
    out = tmp_path / "day.ndjson.gz"
    r = CliRunner().invoke(app, ["export", "--day", "2026-10-01", "--include-off", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert [json.loads(line) for line in gzip.decompress(out.read_bytes()).splitlines()] == export(
        "2026-10-01", include="off")


# What resolve.products did on main before #31: every product of a batch through the merge-following
# SNAPSHOT_SQL, and the record filter as exists-or-not-exists. The export must stay byte-identical to it.
LEGACY_VISIBLE = """(exists (select 1 from observation o where o.food_id = food.id and o.status = 'accepted')
       or not exists (select 1 from observation o where o.food_id = food.id))"""


def legacy_products(pids: list[int], include: str | None, day: date, conn) -> list[dict]:
    from sqlalchemy import text

    from fooddb import resolve

    pids = resolve.canonical(pids, conn)
    params = {"pids": pids, "layers": resolve.layers_for(include), "scope": "all" if include == "off" else "core"}
    records = conn.execute(text(resolve.RECORDS_SQL.replace(resolve.VISIBLE, LEGACY_VISIBLE)), params).mappings().all()
    values = conn.execute(text(resolve.SNAPSHOT_SQL), params | {"day": day}).mappings().all()
    by_pid: dict[int, dict] = {}
    for r in records:
        p = by_pid.setdefault(r["product_id"], {"id": r["product_id"], "records": [], "gtin14": [],
                                                "snapshot": day.isoformat()})
        if not p["records"]:
            p.update({f: resolve.tagged(r, r[f]) for f in resolve.FIELDS}, flags=resolve.tagged(r, list(r["flags"])),
                     per_100={})
        p["records"].append(r["id"])
        if r["gtin14"] and r["gtin14"] not in [g["value"] for g in p["gtin14"]]:
            p["gtin14"].append(resolve.tagged(r, r["gtin14"]))
    for v in values:
        if v["product_id"] in by_pid:
            by_pid[v["product_id"]]["per_100"][v["nutrient"]] = {
                "value": float(v["value_per_100"]), "unit": v["unit"], "basis": v["basis"],
                "source": v["source"], "licence": v["licence"], "observed_at": v["observed_at"],
            }
    for found in by_pid.values():
        found["seals"] = resolve.seals(found["per_100"])
        found["attribution"] = resolve.attribution(found)
    return [by_pid[p] for p in pids if p in by_pid]


def legacy_export(day: date, include: str | None) -> bytes:
    from pydantic_core import to_json
    from sqlalchemy import text

    from fooddb import export as ex
    from fooddb.db import engine

    with engine().connect() as conn:
        ids = conn.execute(text(ex.IDS_SQL), {"day": day, "scope": "all" if include == "off" else "core"}).scalars().all()
        return b"".join(to_json(p) + b"\n" for i in range(0, len(ids), 2)
                        for p in legacy_products(ids[i:i + 2], include, day, conn))


def test_export_bytes_equal_the_per_batch_resolve_it_replaced(monkeypatch):
    from sqlalchemy import text

    from fooddb import export as ex
    from fooddb import ingest
    from fooddb.db import engine
    from tests.test_db import ingest_labels, kcal_record, label_record, merge

    ingest.run("t", "r1", [
        kcal_record("fdc:1", "fdc", 229.0, 2026), kcal_record("ciqual:1", "ciqual", 229.0, 2025),
        kcal_record("off:1", "off", 300.0, 2026), kcal_record("off:2", "off", 310.0, 2025),
        rec(id="fdc:9", name="Lentils, raw", values=HUMMUS | {"SUGAR": 2.0, "NA": 500.0}),
        rec(**OFF), rec(id="fdc:7", name="Held back"), rec(id="fdc:8", name="No values yet", values={}),
    ])
    ingest_labels(label_record("label:aa", 260.0, 1, True))
    with engine().begin() as conn:
        conn.execute(text("update observation set status = 'pending' where food_id = 'fdc:7'"))
    build_on(monkeypatch, "2026-10-01")
    merge("fdc:1", "ciqual:1", "label:aa", "fdc:7", "fdc:8")  # after the build: the survivor has merged-in ids
    merge("off:1", "off:2")
    monkeypatch.setattr(ex, "BATCH", 2)  # batches that mix products with and without merged-in ids
    with engine().connect() as conn:
        assert conn.execute(text("select count(*) from product where merged_into is not null")).scalar_one() == 5
    day = date(2026, 10, 1)
    for include in (None, "off"):
        got = b"".join(ex.lines(day, include))
        assert got and got == legacy_export(day, include)
    assert b"fdc:7" not in got and b"fdc:8" in got  # a record with only pending values is held back; one with none is not
    assert b'"value":260.0' in b"".join(ex.lines(day, None))  # the approved label read won


def test_a_snapshot_build_analyzes_its_table(monkeypatch):
    from sqlalchemy import text

    from fooddb import ingest
    from fooddb.db import engine

    ingest.run("t", "r1", [rec()])
    build_on(monkeypatch, "2026-10-01")
    with engine().connect() as conn:
        assert conn.execute(text("select reltuples from pg_class where relname = 'snapshot_value'")).scalar_one() > 0
