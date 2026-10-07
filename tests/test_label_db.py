"""The label-read lane against a real Postgres: intake, ingest with photo evidence, review rules, the
admin photo page and a local read submitted to a server. Database suite."""

import base64
import json

import pytest

from fooddb.labels import LabelRead, backends
from tests.test_db import clean, client, key, merge, product, pytestmark, rec  # noqa: F401
from tests.test_labels import JPEG, PNG, READ


@pytest.fixture(autouse=True)
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FOODDB__BACKEND__PHOTO_DIR", str(tmp_path))
    monkeypatch.setenv("FOODDB__BACKEND__LABEL_CONFIDENCE_FLOOR", "0.9")


class Canned:
    def __init__(self, **changes):
        self.read_ = LabelRead.model_validate(READ | changes)

    def read(self, image, mime, hints):
        return self.read_


def use(monkeypatch, r) -> None:
    import fooddb.labels

    monkeypatch.setattr(fooddb.labels, "reader", lambda name=None: r)


def observations(record_id: str) -> dict[str, dict]:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return {r["nutrient"]: dict(r) for r in conn.execute(text(
            "select nutrient, value_per_100, status, source, licence, evidence from observation where food_id = :id"
        ), {"id": record_id}).mappings()}


def ingest(image: bytes = PNG, hints: dict | None = None, read: dict | None = None) -> str:
    from fooddb.labels import intake, photos

    sha, _ = photos.store(image)
    return intake.process(sha, hints or {}, read)


def test_a_confident_label_read_becomes_observations_with_the_photo_as_evidence(monkeypatch):
    import hashlib

    use(monkeypatch, Canned())
    rid = ingest()
    sha = hashlib.sha256(PNG).hexdigest()
    assert rid == f"label:{sha}"
    obs = observations(rid)
    assert set(obs) == {"ENERC_KCAL", "ENERC_KJ", "PROCNT", "FAT", "CHOAVL", "SUGAR", "FASAT", "FIBTG", "NA"}
    assert {(o["status"], o["source"], o["licence"], o["evidence"]) for o in obs.values()} == {
        ("accepted", "label", "LicenseRef-fooddb", sha)}
    p = product(rid)
    assert p["gtin14"][0]["value"] == "04006381333931" and p["name"]["value"] == "Hummus classic"
    assert p["serving_g"]["value"] == 30.0 and p["per_100"]["CHOAVL"]["source"] == "label"


def test_label_fields_that_fail_a_check_wait_for_review(monkeypatch):
    use(monkeypatch, Canned(values=READ["values"] | {"ENERC_KCAL": 2290, "SUGAR": 20}))
    obs = observations(ingest())
    assert {k for k, o in obs.items() if o["status"] == "pending"} >= {"ENERC_KCAL", "SUGAR"}
    assert obs["NA"]["status"] == "accepted"


def test_below_the_confidence_floor_every_label_field_waits_for_review(monkeypatch):
    from fooddb import review

    use(monkeypatch, Canned(confidence=0.5))
    rid = ingest()
    assert {o["status"] for o in observations(rid).values()} == {"pending"}
    [item] = review.queue()
    assert item["record"] == rid and "label-low-confidence" in item["checks"]


def test_the_barcode_the_client_scanned_wins_over_the_one_the_model_read(monkeypatch):
    use(monkeypatch, Canned(barcode="96385074"))
    assert product(ingest(hints={"barcode": "4006381333931"}))["gtin14"][0]["value"] == "04006381333931"


def test_a_read_done_by_the_client_waits_for_review_whatever_its_confidence(monkeypatch):
    def server_read(*a):
        raise AssertionError("a client read is not read again")

    use(monkeypatch, type("R", (), {"read": server_read})())
    rid = ingest(read=READ | {"confidence": 1.0})
    assert {o["status"] for o in observations(rid).values()} == {"pending"}


def upload(c, image: bytes = JPEG, **form):
    return c.post("/v1/labels", files={"photo": ("label.jpg", image, "image/jpeg")}, data=form)


def test_label_intake_needs_the_contribute_scope_and_queues_a_read():
    from fooddb import jobs

    assert upload(client()).status_code == 401
    assert upload(client(key("read"))).status_code == 403
    for scope in ("contribute", "review", "admin"):
        r = upload(client(key(scope)), barcode="4006381333931", name="Hummus")
        assert r.status_code == 202, (scope, r.text)
    task = r.json()["task"]
    status = client(key("contribute", name="c2")).get(f"/v1/labels/{task}")
    assert status.status_code == 200 and status.json()["status"] == "pending"
    assert status.json()["record"] == r.json()["record"]
    assert client(key("read", name="r2")).get(f"/v1/labels/{task}").status_code == 403
    assert client(key("contribute", name="c3")).get("/v1/labels/999999999").status_code == 404
    queued = jobs.queue().get_task(task)
    assert queued.name.endswith("read_label") and queued.payload["kwargs"]["hints"] == {
        "barcode": "4006381333931", "name": "Hummus"}


def test_label_intake_refuses_what_is_not_a_photo_or_too_big(monkeypatch):
    from fooddb.labels import photos

    c = client(key("contribute"))
    assert upload(c, b"%PDF-1.7 not an image").status_code == 415
    monkeypatch.setattr(photos, "MAX_BYTES", 100)
    assert upload(c, JPEG + b"\0" * 200).status_code == 413
    monkeypatch.setattr(photos, "MAX_BYTES", 10_000)
    assert upload(c, barcode="123").status_code == 422
    assert upload(c, read="{not json").status_code == 422


def test_the_queued_task_reads_and_ingests_the_label(monkeypatch):
    from fooddb import jobs

    use(monkeypatch, Canned())
    monkeypatch.setattr(jobs, "_rematch", lambda fetcher: None)
    r = upload(client(key("contribute")), barcode="4006381333931").json()
    jobs.read_label(**jobs.queue().get_task(r["task"]).payload["kwargs"])
    assert observations(r["record"])["ENERC_KCAL"]["status"] == "accepted"


def test_a_local_read_submitted_to_a_server_lands_there_for_review(monkeypatch):
    import httpx

    import fooddb.labels

    monkeypatch.setenv("FOODDB__BACKEND__SUBMIT_URL", "http://fooddb.test")
    monkeypatch.setenv("FOODDB__BACKEND__SUBMIT_KEY", key("contribute"))
    sent = {}

    def post(url, **kw):
        sent["url"] = url
        kw.pop("timeout", None)
        return client().post(url.removeprefix("http://fooddb.test"), **kw)

    monkeypatch.setattr(httpx, "post", post)
    use(monkeypatch, backends.Demo())
    from tests.test_labels import mcp_call

    r = mcp_call("read_label", image=base64.b64encode(JPEG).decode(), reader="demo", barcode="4006381333931", submit=True)
    assert not r.is_error, r.content
    assert sent["url"] == "http://fooddb.test/v1/labels"
    from fooddb import jobs

    task = jobs.queue().get_task(r.structured_content["submitted"]["task"])
    assert json.loads(task.payload["kwargs"]["read"])["barcode"] == "4006381333931"


def test_admin_shows_a_label_records_pending_values_next_to_its_photo_and_the_served_values(monkeypatch):
    from fooddb import ingest as ingest_mod

    ingest_mod.run("t", "r1", [rec(gtin14="04006381333931", values={"ENERC_KCAL": 229.0, "PROCNT": 7.4})])
    use(monkeypatch, Canned(confidence=0.5, values=READ["values"] | {"ENERC_KCAL": 231}))
    rid = ingest()
    merge("fdc:1", rid)
    sha = rid.removeprefix("label:")
    c = client()
    assert c.get("/admin/labels", follow_redirects=False).status_code == 302
    assert c.get(f"/admin/labels/photo/{sha}", follow_redirects=False).status_code == 302
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="kirill")},
                  follow_redirects=False).status_code == 302
    page = c.get("/admin/labels")
    assert page.status_code == 200, page.text
    assert f"/admin/labels/photo/{sha}" in page.text and "ENERC_KCAL" in page.text
    assert "231" in page.text and "229" in page.text  # the pending read next to the value served now
    assert '<div class="col-12"><div class="w-100">' in page.text  # Tabler's row-deck makes a bare col-12 a flex row
    photo = c.get(f"/admin/labels/photo/{sha}")
    assert photo.status_code == 200 and photo.content == PNG and photo.headers["content-type"] == "image/png"
    assert c.get("/admin/labels/photo/" + "0" * 64).status_code == 404


def test_a_label_read_below_the_floor_is_not_served_until_a_value_is_accepted(monkeypatch):
    from fooddb import review

    use(monkeypatch, Canned(confidence=0.5))
    rid = ingest()
    c = client()
    assert c.get(f"/v1/records/{rid}").status_code == 404
    assert c.get("/v1/products/4006381333931").status_code == 404
    assert c.get("/v1/foods", params={"q": "hummus"}).json()["items"] == []
    review.decide(review.queue()[0]["pending"][0]["observation_id"], "accept", "tester")
    assert c.get("/v1/products/4006381333931").json()["items"][0]["name"]["value"] == "Hummus classic"
