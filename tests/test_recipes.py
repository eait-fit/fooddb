"""The recipe layer: dishes computed from ingredient records, reviewed once before they serve.
Database suite (see test_db.py); the pure-compute cases run anywhere."""

import pytest

from tests.test_db import clean, client, pytestmark, rec  # noqa: F401


def stew():
    from fooddb.recipes import Ingredient, Recipe

    return Recipe(
        slug="test-stew", name_en="Test stew", name_ru="Тестовая похлёбка",
        citation="fooddb editorial: a test formulation",
        cooked_yield=0.5,
        ingredients=(Ingredient("fdc:1", 200), Ingredient("cofid:2", 100), Ingredient("frida:3", 100)),
        kcal_band=(100, 300))


@pytest.fixture
def registered(monkeypatch):
    """The stew in the module registry, so attribution resolves it."""
    from fooddb import recipes

    r = stew()
    monkeypatch.setattr(recipes, "RECIPES", recipes.RECIPES + (r,))
    return r


def ingredients():
    from fooddb import ingest

    # fdc states CHOCDF (with fibre): the dish carries CHOAVL = CHOCDF − FIBTG, like its EU ingredients.
    ingest.run("t", "r1", [
        rec(id="fdc:1", source="fdc", values={"ENERC_KCAL": 100.0, "PROCNT": 10.0, "CHOCDF": 20.0, "FIBTG": 5.0}),
        rec(id="cofid:2", source="cofid", licence="OGL-UK-3.0",
            values={"ENERC_KCAL": 200.0, "PROCNT": 20.0, "CHOAVL": 10.0}),
        rec(id="frida:3", source="frida", licence="CC-BY-4.0",
            values={"ENERC_KCAL": 50.0, "PROCNT": 5.0, "CHOAVL": 4.0, "SUGAR": 4.0}),
    ])


def pending_ids(record_id: str) -> list[int]:
    from fooddb.db import engine
    from sqlalchemy import text

    with engine().connect() as conn:
        return list(conn.execute(text(
            "select id from observation where food_id = :id and status = 'pending'"), {"id": record_id}).scalars())


def test_recipe_computes_per_100g_from_ingredient_rows_with_yield_applied():
    from fooddb import recipes

    values = {"fdc:1": {"ENERC_KCAL": 100.0, "PROCNT": 10.0, "CHOCDF": 20.0, "FIBTG": 5.0},
              "cofid:2": {"ENERC_KCAL": 200.0, "PROCNT": 20.0, "CHOAVL": 10.0},
              "frida:3": {"ENERC_KCAL": 50.0, "PROCNT": 5.0, "CHOAVL": 4.0, "SUGAR": 4.0}}
    # 400 g raw cook down to 200 g: every value doubles from the raw-weighted mean.
    found, dropped = recipes.compute(stew(), values)
    assert found == {"ENERC_KCAL": pytest.approx(225), "PROCNT": pytest.approx(22.5),
                     "CHOAVL": pytest.approx(22)}
    # FIBTG (50 % of the mass states it) and SUGAR (25 %) fall under the coverage floor.
    assert set(dropped) == {"FIBTG", "SUGAR"}


def test_a_recipe_builds_two_pending_records_on_one_product_and_is_invisible(registered):
    from fooddb import recipes

    ingredients()
    recipes.build([registered])
    q = client().get("/v1/foods", params={"q": "test stew"}).json()
    assert q["items"] == []
    assert client().get("/v1/records/recipe:test-stew").status_code == 404
    assert client().get("/v1/records/recipe:test-stew.ru").status_code == 404
    en, ru = pending_ids("recipe:test-stew"), pending_ids("recipe:test-stew.ru")
    assert len(en) == len(ru) > 0


def test_a_reviewed_recipe_serves_the_computed_values_with_the_licence_union(registered):
    from fooddb import recipes, review

    ingredients()
    recipes.build([registered])
    ids = pending_ids("recipe:test-stew") + pending_ids("recipe:test-stew.ru")
    for i in ids:
        review.decide(i, "accept", "tester")
    p = client().get("/v1/records/recipe:test-stew").json()
    assert p["name"]["value"] == "Test stew"  # the English record names the product
    assert sorted(p["records"]) == ["recipe:test-stew", "recipe:test-stew.ru"]
    kcal = p["per_100"]["ENERC_KCAL"]
    assert (kcal["value"], kcal["source"]) == (pytest.approx(225), "recipe")
    # Most restrictive licence of the ingredients (CC0 < OGL < CC BY); the union is the attribution.
    assert kcal["licence"] == "CC-BY-4.0"
    assert {a["source"] for a in p["attribution"]} == {"cofid", "frida"}
    # The Russian record makes the dish findable by its Russian name.
    hits = client().get("/v1/foods", params={"q": "тестовая"}).json()["items"]
    assert [i["id"] for i in hits] == [p["id"]]


def test_a_second_build_with_unchanged_ingredients_stores_nothing(registered):
    from fooddb import recipes

    ingredients()
    recipes.build([registered])
    assert recipes.build([registered])["observations"] == 0


def test_a_recipe_outside_its_kcal_band_is_flagged(registered):
    from fooddb import recipes

    import dataclasses

    ingredients()
    recipes.build([dataclasses.replace(registered, kcal_band=(10, 20))])
    from fooddb.db import engine, food
    from sqlalchemy import select

    with engine().connect() as conn:
        flags = conn.execute(
            select(food.c.flags).where(food.c.id == "recipe:test-stew")).scalar_one()
    assert "recipe-kcal-outside-band" in flags


def test_recipe_records_are_not_matched_into_other_products(registered):
    from fooddb import match, recipes

    ingredients()
    recipes.build([registered])
    assert {r["unique_id"] for r in match._records()}.isdisjoint(
        {"recipe:test-stew", "recipe:test-stew.ru"})


def observation_rows(record_id: str) -> list[dict]:
    from sqlalchemy import text

    from fooddb.db import engine

    with engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "select nutrient, value_per_100, status, reviewed_by, review_note from observation "
            "where food_id = :id order by nutrient, observed_at, id"), {"id": record_id}).mappings()]


def test_a_rebuild_rejects_the_pending_set_its_new_values_supersede(registered):
    from datetime import UTC, datetime

    from fooddb import ingest, recipes

    ingredients()
    recipes.build([registered])
    # The ingredient's newer accepted values change the computed dish: the rebuild stores a new set.
    ingest.run("t", "r2", [rec(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        values={"ENERC_KCAL": 120.0, "PROCNT": 11.0, "CHOCDF": 24.0, "FIBTG": 5.0})])
    recipes.build([registered])
    rows = observation_rows("recipe:test-stew")
    pending = [r for r in rows if r["status"] == "pending"]
    superseded = [r for r in rows if r["status"] == "rejected"]
    assert {r["nutrient"] for r in pending} == {"ENERC_KCAL", "PROCNT", "CHOAVL"}
    assert {r["nutrient"] for r in superseded} == {"ENERC_KCAL", "PROCNT", "CHOAVL"}
    assert {r["reviewed_by"] for r in superseded} == {"fooddb:recipes"}
    assert all(r["review_note"].startswith("superseded by recipe rebuild ") for r in superseded)


def test_a_retired_recipe_loses_its_queue_and_stops_serving(registered, monkeypatch):
    from datetime import UTC, datetime

    from fooddb import ingest, recipes, review

    ingredients()
    recipes.build([registered])
    for i in pending_ids("recipe:test-stew") + pending_ids("recipe:test-stew.ru"):
        review.decide(i, "accept", "tester")
    assert client().get("/v1/records/recipe:test-stew").status_code == 200
    # A changed ingredient leaves a second, unreviewed set when the slug leaves the registry.
    ingest.run("t", "r2", [rec(
        observed_at=datetime(2026, 6, 1, tzinfo=UTC),
        values={"ENERC_KCAL": 120.0, "PROCNT": 11.0, "CHOCDF": 24.0, "FIBTG": 5.0})])
    recipes.build([registered])
    monkeypatch.setattr(recipes, "RECIPES", ())
    result = recipes.build(())
    assert {"recipe:test-stew", "recipe:test-stew.ru"} <= set(result["retired"])
    rows = observation_rows("recipe:test-stew") + observation_rows("recipe:test-stew.ru")
    assert not [r for r in rows if r["status"] == "pending"]  # nothing waits for review any more
    retired = [r for r in rows if r["status"] == "rejected"]
    assert {r["nutrient"] for r in retired} == {"ENERC_KCAL", "PROCNT", "CHOAVL"}
    assert {(r["reviewed_by"], r["review_note"]) for r in retired} == {("fooddb:recipes", "recipe retired")}
    # Every nutrient the record served is withdrawn by an accepted null: the orphan serves nothing.
    withdrawn = [r for r in rows
                 if r["status"] == "accepted" and r["value_per_100"] is None]
    assert {r["nutrient"] for r in withdrawn} == {"ENERC_KCAL", "PROCNT", "CHOAVL"}
    assert {(r["reviewed_by"], r["review_note"]) for r in withdrawn} == {("fooddb:recipes", "recipe retired")}
    p = client().get("/v1/records/recipe:test-stew").json()
    assert p["per_100"] == {}


def test_an_uncomputable_recipe_is_a_warning_named_in_the_result(registered):
    from loguru import logger

    from fooddb import recipes

    seen = []
    sink = logger.add(lambda m: seen.append(m.record["message"]), level="WARNING")
    try:
        result = recipes.build([registered])  # no ingredients() run: nothing accepted
    finally:
        logger.remove(sink)
    assert result["recipes"] == 0 and result["skipped"] == 1
    assert result["uncomputable"] == {"test-stew": ["fdc:1", "cofid:2", "frida:3"]}
    assert [m for m in seen if "test-stew" in m and "fdc:1" in m]
