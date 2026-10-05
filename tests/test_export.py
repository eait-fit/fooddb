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
