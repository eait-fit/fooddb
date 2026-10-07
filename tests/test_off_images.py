"""OFF photo references: stored at ingest, backfilled for the records that wait for review, hotlinked on the Review card. Database suite."""

from datetime import UTC, datetime

import httpx
import pytest

from tests.test_db import HUMMUS, TYPO, clean, rec, pytestmark  # noqa: F401
from tests.test_ops import admin, rows

CODE = "08002330009380"
FRONT = "https://images.openfoodfacts.org/images/products/800/233/000/9380/front_it.12.400.jpg"
NUTRITION = "https://images.openfoodfacts.org/images/products/800/233/000/9380/nutrition_it.4.400.jpg"
REFS = {"front": {"lang": "it", "rev": 12}, "nutrition": {"lang": "it", "rev": 4}}


def off(code: str = CODE, **kw):
    return rec(id=f"off:{code}", source="off", layer="off", licence="ODbL-1.0", gtin14=code, name="Pasta", **kw)


def images(record: str = f"off:{CODE}"):
    [row] = rows("select images from food where id = :i", i=record)
    return row["images"]


def waiting(code: str):
    """An OFF record with pending values: a good read, then a typo in energy."""
    from fooddb import ingest

    ingest.run("t", f"good-{code}", [off(code, values=HUMMUS)])
    ingest.run("t", f"typo-{code}", [off(code, observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=TYPO)])


def test_ingest_stores_the_reference_and_an_image_change_alone_updates_the_row_without_observations():
    from fooddb import ingest

    assert ingest.run("t", "r1", [off(images=REFS)]) == (1, 2)
    assert images() == REFS
    assert ingest.run("t", "r1", [off(images=REFS)]) == (1, 0)  # idempotent
    new = {"front": {"lang": "it", "rev": 13}}
    assert ingest.run("t", "r2", [off(images=new)]) == (1, 0)  # same values, new photo: the row changes, no observation
    assert images() == new and rows("select count(*) n from observation")[0]["n"] == 2
    older = off(images=REFS, observed_at=datetime(2025, 1, 1, tzinfo=UTC))
    ingest.run("t", "r3", [older])
    assert images() == new  # a late older file does not roll it back
    ingest.run("t", "r4", [off(images={})])
    assert images() == {}  # OFF dropped its photos: checked, none


def test_only_off_records_that_were_not_asked_have_no_reference():
    from fooddb import ingest

    ingest.run("t", "r1", [rec(), off(images=None)])
    assert images("fdc:1") is None and images() is None
    assert rows("select count(*) n from food where images is null")[0]["n"] == 2  # SQL null, not a JSON null


def mock(responses: dict[str, tuple[int, dict]], calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = responses[request.url.path.rsplit("/", 1)[1].removesuffix(".json")]
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_the_backfill_asks_OFF_only_for_records_with_pending_values_and_no_reference():
    from fooddb import ingest
    from fooddb.fetchers import off as fetcher

    waiting(CODE)
    waiting("04006381333931")  # OFF has no such product: 404
    waiting("05449000000996")  # a product without photos
    ingest.run("t", "fine", [off("03017620422003", values=HUMMUS)])  # nothing pending: not asked
    ingest.run("t", "has", [off("03168930010883", images=REFS, values=HUMMUS | {"PROCNT": 99})])
    ingest.run("t", "fdc", [rec(values=TYPO), rec(observed_at=datetime(2026, 7, 1, tzinfo=UTC), values=HUMMUS | {"FAT": 90})])  # not OFF
    calls: list = []
    answers = {
        "8002330009380": (200, {"code": "8002330009380", "status": 1, "product": {"lang": "it", "images": {
            "1": {"uploader": "x"}, "front_it": {"imgid": "1", "rev": "12"}, "nutrition_it": {"imgid": "2", "rev": "4"}}}}),
        "4006381333931": (404, {"status": 0, "status_verbose": "product not found"}),
        "5449000000996": (200, {"status": 1, "product": {"lang": "fr", "images": {"1": {"uploader": "x"}}}}),
    }
    assert fetcher.backfill_images(pause=0, transport=mock(answers, calls)) == (3, 1)
    assert sorted(c.url.path.rsplit("/", 1)[1] for c in calls) == ["4006381333931.json", "5449000000996.json", "8002330009380.json"]
    assert all(c.headers["user-agent"].startswith("fooddb-images/") and c.url.params["fields"] == "images,lang" for c in calls)
    assert images() == REFS
    assert images("off:04006381333931") == images("off:05449000000996") == {}  # the marker: asked, nothing to show
    assert images("off:03017620422003") is None and images("off:03168930010883") == REFS
    calls.clear()
    assert fetcher.backfill_images(pause=0, transport=mock({}, calls)) == (0, 0) and not calls  # nothing is asked twice


def test_the_backfill_stops_on_a_rate_limit_and_the_next_run_resumes():
    from fooddb.fetchers import off as fetcher

    codes = ["04006381333931", "05449000000996", CODE]
    for c in codes:
        waiting(c)
    calls: list = []
    answers = {"4006381333931": (404, {}), "5449000000996": (429, {}), "8002330009380": (404, {})}
    with pytest.raises(RuntimeError, match="429 after 1 products"):
        fetcher.backfill_images(pause=0, transport=mock(answers, calls))
    assert images("off:04006381333931") == {} and images("off:05449000000996") is None and images() is None
    answers["5449000000996"] = (404, {})
    assert fetcher.backfill_images(pause=0, transport=mock(answers, calls)) == (2, 0)
    assert fetcher.backfill_images(limit=1, pause=0, transport=mock({}, calls)) == (0, 0)


def test_the_job_is_queued_with_a_long_runtime_limit():
    from fooddb import jobs

    task = jobs.enqueue("off-images", limit=5)
    [row] = rows("select payload, max_runtime_seconds from pq_tasks where id = :i", i=task)
    assert row["payload"]["kwargs"] == {"limit": 5} and row["max_runtime_seconds"] == jobs.RUNTIME["off-images"]


def test_the_review_card_shows_the_front_and_nutrition_photos_of_a_record_that_has_a_reference():
    from fooddb import ingest

    waiting(CODE)
    ingest.run("t", "img", [off(images=REFS, observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=TYPO)])
    page = admin().get("/admin/review").text
    for url, kind in ((FRONT, "front"), (NUTRITION, "nutrition")):
        assert f'<a href="{url}" target="_blank" rel="noopener noreferrer">' in page
        assert f'<img src="{url}" alt="{kind} photo" loading="lazy" referrerpolicy="no-referrer"' in page
    assert "Photo: " in page and 'href="https://world.openfoodfacts.org/product/8002330009380"' in page
    assert "Open Food Facts contributors</a>, <a href=\"https://creativecommons.org/licenses/by-sa/3.0/\"" in page and "CC BY-SA 3.0" in page


def test_a_card_without_a_reference_shows_no_image_and_a_label_photo_card_is_unchanged():
    from fooddb import ingest

    waiting(CODE)  # images null: never asked
    waiting("05449000000996")
    ingest.run("t", "none", [off("05449000000996", images={}, observed_at=datetime(2026, 6, 1, tzinfo=UTC), values=TYPO)])
    page = admin().get("/admin/review").text
    assert page.count("review-card") >= 2 and "<img" not in page and "Open Food Facts contributors" not in page
    assert "images.openfoodfacts.org" not in page
    assert "images" not in __import__("fooddb.review", fromlist=["queue"]).queue()[0]  # the REST and MCP queue keeps its shape


def test_the_public_api_does_not_expose_the_image_reference():
    from tests.test_db import client

    from fooddb import ingest

    ingest.run("t", "r1", [off(images=REFS)])
    body = client().get(f"/v1/records/off:{CODE}", params={"include": "off"}).text
    assert "images" not in body and "front_it" not in body and "rev" not in body
