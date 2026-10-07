"""The brand lane against a real Postgres: upload, GS1 verdicts, review, the admin page and the HTML form. Database suite."""

import hashlib
import itertools

import pytest

from tests.test_db import clean, client, key, merge, pytestmark, rec  # noqa: F401
from tests.test_labels import JPEG, PNG

COUNTER = itertools.count()
GTIN = "04006381333931"
FORM = {"barcode": "4006381333931", "name": "Acme Hummus", "brand": "Acme", "basis": "100g",
        "ENERC_KCAL": "229", "PROCNT": "7.4", "FAT": "17.1", "serving_text": "2 tbsp (30 g)", "serving_g": "30"}


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    import fooddb.jobs

    monkeypatch.setenv("FOODDB__BACKEND__PHOTO_DIR", str(tmp_path))
    monkeypatch.delenv("FOODDB__BACKEND__GS1_VERIFIER", raising=False)
    monkeypatch.setattr(fooddb.jobs, "_rematch", lambda fetcher: None)


def verdict(monkeypatch, answer: str) -> None:
    from fooddb import gs1

    monkeypatch.setattr(gs1, "verifier", lambda name=None: type("V", (), {"verify": lambda self, g, b: answer})())


def upload(c, photo: bytes | None = JPEG, **form):
    files = {"photo": ("label.jpg", photo, "image/jpeg")} if photo is not None else None
    return c.post("/v1/brands/uploads", data=FORM | form, files=files)


def contributor():
    return client(key("contribute", name=f"brand-{next(COUNTER)}"))


def observations(record_id: str = f"brand:{GTIN}") -> dict[str, dict]:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return {r["nutrient"]: dict(r) for r in conn.execute(text(
            "select nutrient, value_per_100, status, source, licence, evidence from observation where food_id = :id"
        ), {"id": record_id}).mappings()}


def flags(record_id: str = f"brand:{GTIN}") -> list[str]:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return list(conn.execute(text("select flags from food where id = :i"), {"i": record_id}).scalar_one())


def test_an_upload_needs_the_contribute_scope():
    assert upload(client()).status_code == 401
    assert upload(client(key("read"))).status_code == 403
    for scope in ("contribute", "review", "admin"):
        assert upload(client(key(scope, name=scope))).status_code == 201, scope


@pytest.mark.parametrize("barcode", ["123", "4006381333930", "0400000000008", "abc", ""])
def test_the_barcode_must_be_a_valid_global_gtin(barcode):
    r = upload(contributor(), barcode=barcode)
    assert r.status_code == 422 and "barcode" in r.text


def test_the_label_photo_is_required_and_checked_by_its_magic_bytes(monkeypatch):
    from fooddb.labels import photos

    c = contributor()
    assert upload(c, photo=None).status_code == 422
    assert upload(c, photo=b"").status_code == 422
    assert upload(c, photo=b"%PDF-1.7 not an image").status_code == 415
    monkeypatch.setattr(photos, "MAX_BYTES", 100)
    assert upload(c, photo=JPEG + b"\0" * 200).status_code == 413
    assert observations() == {}  # nothing was ingested


@pytest.mark.parametrize("change", [
    {"name": ""}, {"brand": " "}, {"basis": "serving"}, {"ENERC_KCAL": "abc"}, {"ENERC_KCAL": "-1"},
    {"ENERC_KCAL": "nan"}, {"serving_g": "0"}, {"serving_g": "x"},
])
def test_the_fields_are_validated(change):
    assert upload(contributor(), **change).status_code == 422
    assert observations() == {}


def test_at_least_one_value_is_required():
    r = upload(contributor(), ENERC_KCAL="", PROCNT="", FAT="")
    assert r.status_code == 422 and "value" in r.text


def test_an_unverified_upload_waits_for_review_in_full_and_is_not_served():
    sha = hashlib.sha256(JPEG).hexdigest()
    r = upload(contributor())
    assert r.status_code == 201, r.text
    assert r.json() == {"record": f"brand:{GTIN}", "photo": sha, "verification": "unknown", "review": "required"}
    obs = observations()
    assert set(obs) == {"ENERC_KCAL", "PROCNT", "FAT"}
    assert {(o["status"], o["source"], o["licence"], o["evidence"]) for o in obs.values()} == {
        ("pending", "brand", "LicenseRef-fooddb", sha)}
    assert flags() == ["brand-unverified"]
    c = client()
    assert c.get("/v1/products/4006381333931").status_code == 404
    assert c.get(f"/v1/records/brand:{GTIN}").status_code == 404
    assert c.get("/v1/foods", params={"q": "hummus"}).json()["items"] == []


@pytest.mark.parametrize("answer", ["not_verified", "unknown"])
def test_a_verdict_short_of_verified_holds_everything(monkeypatch, answer):
    verdict(monkeypatch, answer)
    assert upload(contributor()).json()["review"] == "required"
    assert {o["status"] for o in observations().values()} == {"pending"}
    assert ("brand-gs1-mismatch" in flags()) == (answer == "not_verified")
    assert "brand-unverified" in flags()


def test_a_verifier_that_raises_holds_everything(monkeypatch):
    from fooddb import gs1

    def boom(self, g, b):
        raise RuntimeError("down")

    monkeypatch.setattr(gs1, "verifier", lambda name=None: type("V", (), {"verify": boom})())
    assert upload(contributor()).status_code == 201
    assert {o["status"] for o in observations().values()} == {"pending"}


def test_a_verified_upload_is_served_and_ranks_above_the_tables(monkeypatch):
    from fooddb import ingest

    ingest.run("t", "r1", [rec(gtin14=GTIN, values={"ENERC_KCAL": 250.0})])
    verdict(monkeypatch, "verified")
    r = upload(contributor())
    assert r.json()["review"] == "checks only" and flags() == []
    assert {o["status"] for o in observations().values()} == {"accepted"}
    merge("fdc:1", f"brand:{GTIN}")
    p = client().get("/v1/products/4006381333931").json()["items"][0]
    assert p["per_100"]["ENERC_KCAL"]["source"] == "brand" and p["per_100"]["ENERC_KCAL"]["value"] == 229
    assert p["name"]["source"] == "brand" and p["gtin14"][0]["value"] == GTIN
    assert p["serving_g"]["value"] == 30.0


def test_a_verified_upload_still_goes_through_the_checks(monkeypatch):
    verdict(monkeypatch, "verified")
    assert upload(contributor(), CHOAVL="9.6", SUGAR="20", NA="400").status_code == 201
    obs = observations()
    assert obs["SUGAR"]["status"] == "pending" and obs["NA"]["status"] == "accepted"


def test_an_unverified_second_upload_changes_neither_the_served_values_nor_the_served_metadata(monkeypatch):
    verdict(monkeypatch, "verified")
    upload(contributor())
    verdict(monkeypatch, "unknown")
    assert upload(contributor(), ENERC_KCAL="300", name="Evil Hummus", serving_g="99").status_code == 201
    p = client().get("/v1/products/4006381333931").json()["items"][0]
    assert p["per_100"]["ENERC_KCAL"]["value"] == 229
    assert p["name"]["value"] == "Acme Hummus" and p["serving_g"]["value"] == 30.0


def test_the_upload_queues_a_match_pass(monkeypatch):
    import fooddb.jobs

    seen = []
    monkeypatch.setattr(fooddb.jobs, "_rematch", seen.append)
    upload(contributor())
    assert seen == ["brand"]


def test_review_lists_the_upload_and_accepting_a_value_serves_it():
    from fooddb import review

    upload(contributor())
    [item] = client(key("review", name="rev")).get("/v1/review").json()["items"]
    assert item["record"] == f"brand:{GTIN}" and item["source"] == "brand" and "brand-unverified" in item["checks"]
    obs = next(v["observation_id"] for v in item["pending"] if v["nutrient"] == "PROCNT")
    review.decide(obs, "accept", "tester")
    p = client().get("/v1/products/4006381333931").json()["items"][0]
    assert p["per_100"]["PROCNT"]["source"] == "brand" and "ENERC_KCAL" not in p["per_100"]


def test_admin_shows_a_brand_upload_next_to_its_photo():
    upload(contributor(), photo=PNG)
    sha = hashlib.sha256(PNG).hexdigest()
    c = client()
    assert c.post("/admin/login", data={"username": "", "password": key("admin", name="kirill")},
                  follow_redirects=False).status_code == 302
    page = c.get("/admin/review")
    assert page.status_code == 200, page.text
    assert f"/admin/review/photo/{sha}" in page.text and "Acme Hummus" in page.text and "brand-unverified" in page.text
    assert c.get(f"/admin/review/photo/{sha}").content == PNG


def post_form(c, photo: bytes | None = JPEG, **form):
    files = {"photo": ("label.jpg", photo, "image/jpeg")} if photo is not None else None
    return c.post("/brands/upload", data=FORM | form, files=files)


def test_the_form_renders_with_a_password_field_and_is_not_cached():
    r = client().get("/brands/upload")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'type="password"' in r.text and 'name="photo"' in r.text and "ENERC_KCAL" in r.text
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


def test_the_form_posts_an_upload_with_a_contribute_key():
    token = key("contribute")
    r = post_form(client(), key=token)
    assert r.status_code == 200, r.text
    assert f"brand:{GTIN}" in r.text and "wait for review" in r.text
    assert token not in r.text and r.headers["cache-control"] == "no-store"
    assert {o["status"] for o in observations().values()} == {"pending"}


def test_the_form_refuses_a_missing_wrong_or_read_only_key_and_never_echoes_it():
    assert post_form(client()).status_code == 401
    r = post_form(client(), key="fdb_wrong")
    assert r.status_code == 401 and "fdb_wrong" not in r.text
    ro = key("read")
    r = post_form(client(), key=ro)
    assert r.status_code == 403 and ro not in r.text
    assert observations() == {}


def test_the_form_shows_the_problem_and_keeps_what_was_typed():
    token = key("contribute")
    r = post_form(client(), key=token, barcode="123", name="Typed name")
    assert r.status_code == 422 and "barcode" in r.text and "Typed name" in r.text and token not in r.text
    assert post_form(client(), photo=None, key=token).status_code == 422
    assert post_form(client(), photo=b"%PDF-1.7", key=token).status_code == 415
