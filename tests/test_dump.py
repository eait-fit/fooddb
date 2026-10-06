"""Monthly ODbL dump of the OFF-derived layer: the job, the files, the public endpoints. Database suite."""

import gzip
import hashlib
import json
from datetime import date

import pytest

from tests.test_db import OneOffQueue, build_on, clean, client, key, merge, pytestmark, rec  # noqa: F401
from tests.test_export import OFF

ODBL = "ODbL-1.0"
# A second OFF record for the hummus: FDC wins its energy by rank, sugar has no other source.
OFF_HUMMUS = dict(id="off:00000000000017", source="off", layer="off", licence=ODBL, gtin14="00000000000017",
                  name="Hummus, store brand", values={"ENERC_KCAL": 300.0, "SUGAR": 0.4})


@pytest.fixture
def dumps(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODDB__BACKEND__DUMP_DIR", str(tmp_path))
    return tmp_path


def on_day(monkeypatch, day: str) -> None:
    from fooddb import snapshot

    monkeypatch.setattr(snapshot, "today", lambda: date.fromisoformat(day))


def dump_lines(path) -> list[dict]:
    return [json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]


def licences(node) -> list[str]:
    if isinstance(node, dict):
        return ([node["licence"]] if "licence" in node else []) + [x for v in node.values() for x in licences(v)]
    if isinstance(node, list):
        return [x for v in node for x in licences(v)]
    return []


def fixture_days(monkeypatch) -> None:
    from fooddb import ingest

    ingest.run("t", "r1", [rec(), rec(**OFF_HUMMUS), rec(**OFF), rec(id="fdc:9", name="Lentils, raw")])
    merge("fdc:1", "off:00000000000017")
    build_on(monkeypatch, "2026-10-01")
    build_on(monkeypatch, "2026-10-02")  # today: not final, so not dumped


def test_job_dumps_only_the_odbl_part_of_the_newest_final_day(monkeypatch, dumps):
    from fooddb import jobs

    fixture_days(monkeypatch)
    jobs.dump_odbl()

    name = "fooddb-off-odbl-2026-10-01.ndjson.gz"
    manifest = json.loads((dumps / "fooddb-off-odbl-2026-10-01.json").read_text())
    data = (dumps / name).read_bytes()
    assert manifest["name"] == name and manifest["day"] == "2026-10-01" and manifest["products"] == 2
    assert (manifest["size"], manifest["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())
    assert manifest["licence"] == ODBL and "Open Food Facts" in manifest["attribution"]
    assert manifest["terms"].endswith("docs/data-licence.md") and manifest["generated_at"]

    lines = dump_lines(dumps / name)
    assert set(licences(lines)) == {ODBL}
    assert "CC0" not in gzip.decompress(data).decode()
    by_record = {p["records"][0]: p for p in lines}
    assert sorted(by_record) == ["off:00000000000017", "off:04006381333931"]
    hummus = by_record["off:00000000000017"]
    assert hummus["records"] == ["off:00000000000017"]  # fdc:1 is in the product, but not ODbL
    assert hummus["per_100"] == {"SUGAR": hummus["per_100"]["SUGAR"]}  # FDC's energy and protein won
    assert hummus["name"] is None  # FDC names the product
    assert [g["value"] for g in hummus["gtin14"]] == ["00000000000017"]
    assert hummus["snapshot"] == "2026-10-01"
    full = client().get(f"/v1/foods/{hummus['id']}", params={"include": "off", "snapshot": "2026-10-01"}).json()
    assert hummus["per_100"]["SUGAR"] == full["per_100"]["SUGAR"]  # the dump links back to the API by id
    spread = by_record["off:04006381333931"]
    assert spread["name"]["value"] == "Hummus classic" and spread["per_100"]["ENERC_KCAL"]["value"] == 300


def test_no_final_day_writes_nothing(monkeypatch, dumps):
    from fooddb import dump, ingest

    ingest.run("t", "r1", [rec(**OFF)])
    build_on(monkeypatch, "2026-10-01")
    assert dump.write() is None
    assert list(dumps.iterdir()) == []


def test_only_the_newest_dumps_are_kept(monkeypatch, dumps):
    from fooddb import dump, ingest

    ingest.run("t", "r1", [rec(**OFF)])
    for day in ("2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01"):
        build_on(monkeypatch, day)
        on_day(monkeypatch, "2026-12-31")
        dump.write()
    assert sorted(p.name for p in dumps.iterdir()) == [
        f"fooddb-off-odbl-2026-{m}-01.{ext}" for m in ("08", "09", "10") for ext in ("json", "ndjson.gz")]
    monkeypatch.setenv("FOODDB__BACKEND__DUMP_KEEP", "1")
    dump.write()
    assert [m["day"] for m in dump.manifests()] == ["2026-10-01"]


def test_dumps_are_public_even_when_reads_need_a_key(monkeypatch, dumps):
    from fooddb import dump

    fixture_days(monkeypatch)
    dump.write()
    monkeypatch.setenv("FOODDB__BACKEND__REQUIRE_KEY_FOR_READS", "true")
    assert client().get("/v1/snapshots").status_code == 401

    items = client().get("/v1/dumps").json()["items"]
    assert [m["name"] for m in items] == ["fooddb-off-odbl-2026-10-01.ndjson.gz"]
    r = client().get(f"/v1/dumps/{items[0]['name']}")
    assert r.status_code == 200 and r.content == (dumps / items[0]["name"]).read_bytes()
    assert r.headers["content-type"] == "application/gzip" and "content-encoding" not in r.headers
    assert 'attachment; filename="fooddb-off-odbl-2026-10-01.ndjson.gz"' in r.headers["content-disposition"]
    assert r.headers["etag"] == f'"{items[0]["sha256"]}"'
    unchanged = client().get(f"/v1/dumps/{items[0]['name']}", headers={"If-None-Match": r.headers["etag"]})
    assert unchanged.status_code == 304 and not unchanged.content
    assert client(key("read")).get("/v1/dumps").status_code == 200
    assert client("fdb_not-a-key").get("/v1/dumps").status_code == 401
    for bad in ("nope.ndjson.gz", "fooddb-off-odbl-2026-10-01.json", "..%2F..%2Fetc%2Fpasswd"):
        assert client().get(f"/v1/dumps/{bad}").status_code == 404, bad


def test_dumps_count_against_the_per_ip_rate_limit(monkeypatch, dumps):
    monkeypatch.setenv("FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE", "1")
    assert [client().get("/v1/dumps").status_code for _ in range(2)] == [200, 429]


def test_cli_dump_writes_into_out(monkeypatch, dumps, tmp_path_factory):
    from typer.testing import CliRunner

    from fooddb.cli import app

    fixture_days(monkeypatch)
    out = tmp_path_factory.mktemp("out")
    r = CliRunner().invoke(app, ["dump", "odbl", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert sorted(p.name for p in out.iterdir()) == ["fooddb-off-odbl-2026-10-01.json",
                                                     "fooddb-off-odbl-2026-10-01.ndjson.gz"]
    assert list(dumps.iterdir()) == []


def test_worker_schedules_the_dump_monthly(monkeypatch):
    from pq import Priority

    from fooddb import jobs

    class Recording(OneOffQueue):
        def schedule(self, fn, **kwargs):
            self.scheduled = getattr(self, "scheduled", {}) | {fn.__name__: kwargs}

    q = Recording()
    monkeypatch.setattr(jobs, "queue", lambda: q)
    jobs.schedule()
    assert q.scheduled["dump_odbl"] == {"cron": "0 4 1 * *", "priority": Priority.BATCH}
