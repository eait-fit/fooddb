"""Recipes: dishes computed from ingredient records — their values are never typed in.

Each recipe names the ingredient records of the composition tables (fdc, bls, ciqual, cofid, …)
with their grams in the raw mix, a cooked yield (the cooked dish's weight divided by the raw mix;
a water-loss factor below 1, a gain above) and the citation of its formulation. `compute` weighs
each ingredient's newest accepted per-100 g values into the cooked dish's; `build` stores them
through the normal ingest path with `review_all`, so every value waits in the review queue and a
recipe stays invisible until a person accepts it once.

One recipe makes two records on one product (`ingest.Record.group`): `recipe:<slug>` with the
English name the eait matcher keys on, `recipe:<slug>.ru` with the Russian one. Both hold the same
computed values, so the Russian record is invisible too until it is reviewed.

Carbohydrate is normalised to CHOAVL: an ingredient that only states CHOCDF (by difference, fibre
inside) and FIBTG gives CHOAVL = CHOCDF − FIBTG, so a recipe can mix US and EU sources.

The licence of a recipe record and its values is the most restrictive among its ingredients'
licences (`resolve.LICENCES` order); the attribution of a served recipe product is the union of the
sources that gave an ingredient — `resolve.attribution` reads `ingredient_sources` from the
registry, so it stays right when a formulation is edited.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from fooddb import ingest
from fooddb.db import engine

SOURCE = "recipe"
MIN_COVERAGE = 0.9  # a nutrient is computed when ingredients with a stated value make ≥90 % of the raw mix
OUTLIER_FLAG = "recipe-kcal-outside-band"
# Computed values keep ~6 significant digits: that is far beyond what a formulation justifies, and a value
# that survives the wire to `numeric` unchanged is what the ingest diff compares against — anything longer
# arrives rounded to 15 digits and every rebuild would store a "new" value that waits for review again.
DIGITS = 6


@dataclass(frozen=True)
class Ingredient:
    record: str  # a food record id, e.g. "bls:C214200"
    grams: float  # its weight in the raw mix


@dataclass(frozen=True)
class Recipe:
    slug: str
    name_en: str  # the eait matcher keys on English names
    name_ru: str
    citation: str  # a public recipe, or "fooddb editorial: <reasoning>"
    ingredients: tuple[Ingredient, ...]
    cooked_yield: float = 1.0  # cooked weight ÷ raw mix
    kcal_band: tuple[float, float] | None = None  # plausible kcal/100 g; outside it the dish is flagged
    serving_g: float | None = None


I = Ingredient

# The first set from #84: the RU/KZ/Central Asian table gap, computed from the tables we hold.
RECIPES: tuple[Recipe, ...] = (
    Recipe("plov", "Plov", "Плов",
           "fooddb editorial: Uzbek-style plov — rice, lamb, carrot and onion fried in oil, then steamed with "
           "water; ~0.88 of the raw mix survives as the served dish (evaporation past the rice's uptake)",
           (I("bls:C352000", 250), I("bls:U807000", 200), I("bls:G620100", 150), I("bls:G480100", 100),
            I("bls:Q320000", 80), I("ciqual:18066", 450), I("ciqual:11017", 8), I("bls:G490100", 10)),
           cooked_yield=0.88, kcal_band=(140, 260), serving_g=300),
    Recipe("beshbarmak", "Beshbarmak", "Бешбармак",
           "fooddb editorial: boiled fatty mutton and lamb over boiled noodle sheets with onion and a ladle "
           "of broth — the Kazakh serving, nothing evaporates once plated",
           (I("bls:U856132", 200), I("bls:U867132", 200), I("bls:E432032", 400), I("bls:G480100", 80),
            I("ciqual:18066", 120)),
           cooked_yield=1.0, kcal_band=(140, 260), serving_g=350),
    Recipe("manty", "Manty", "Манты",
           "fooddb editorial: steamed lamb dumplings — unleavened dough (flour, water, egg) around minced lamb "
           "with onion and tail fat (mutton tallow); steaming loses ~10 % of the raw weight",
           (I("bls:C214200", 200), I("ciqual:18066", 80), I("bls:E111100", 25), I("ciqual:11017", 7),
            I("bls:U807000", 150), I("bls:Q880000", 30), I("bls:G480100", 100)),
           cooked_yield=0.9, kcal_band=(170, 280), serving_g=250),
    Recipe("pelmeni", "Pelmeni", "Пельмени",
           "fooddb editorial: boiled dumplings — unleavened dough around mixed beef-pork mince with onion; "
           "boiled dumplings take up a little water, so the cooked weight slightly exceeds the raw one",
           (I("bls:C214200", 200), I("ciqual:18066", 80), I("bls:E111100", 25), I("ciqual:11017", 7),
            I("bls:U050100", 250), I("bls:G480100", 60)),
           cooked_yield=1.05, kcal_band=(170, 270), serving_g=200),
    Recipe("vareniki", "Vareniki, potato filling", "Вареники с картофелем",
           "fooddb editorial: boiled dumplings — unleavened dough around mashed boiled potato with onion "
           "fried in butter",
           (I("bls:C214200", 200), I("ciqual:18066", 80), I("bls:E111100", 25), I("ciqual:11017", 5),
            I("bls:K110132", 250), I("bls:G480100", 50), I("bls:Q6A4000", 15)),
           cooked_yield=1.02, kcal_band=(130, 220), serving_g=250),
    Recipe("syrniki", "Syrniki", "Сырники",
           "fooddb editorial: fried curd fritters — tvorog (the pressed quark mix of the tvorog recipe: "
           "450 g quark 20 % + 113 g quark 40 % press to ≈400 g once the whey leaves) with egg, a little "
           "flour and sugar, fried in sunflower oil; ~10 % of the raw weight goes as steam",
           (I("bls:M713300", 450), I("bls:M713500", 113), I("bls:E111100", 50), I("bls:C214200", 60),
            I("bls:S111000", 30), I("ciqual:11017", 1), I("bls:Q320000", 15)),
           cooked_yield=0.696, kcal_band=(190, 280), serving_g=180),
    Recipe("borscht", "Borscht", "Борщ",
           "fooddb editorial: beet soup on beef — beets, cabbage and potato with carrot and onion fried in "
           "sunflower oil, tomato paste, simmered; ~5 % of the pot evaporates",
           (I("ciqual:18066", 600), I("bls:U184100", 120), I("bls:G613100", 150), I("bls:G342100", 100),
            I("bls:K110100", 150), I("bls:G620100", 50), I("bls:G480100", 50), I("bls:R160000", 20),
            I("bls:Q320000", 15), I("ciqual:11017", 6)),
           cooked_yield=0.95, kcal_band=(35, 80), serving_g=300),
    Recipe("shchi", "Shchi", "Щи",
           "fooddb editorial: cabbage soup on beef — cabbage and potato with carrot and onion fried in "
           "sunflower oil, a spoon of tomato paste, simmered; ~5 % of the pot evaporates",
           (I("ciqual:18066", 600), I("bls:U184100", 120), I("bls:G342100", 200), I("bls:K110100", 150),
            I("bls:G620100", 40), I("bls:G480100", 50), I("bls:R160000", 15), I("bls:Q320000", 10),
            I("ciqual:11017", 6)),
           cooked_yield=0.95, kcal_band=(30, 70), serving_g=300),
    Recipe("olivier", "Olivier salad", "Оливье",
           "fooddb editorial: boiled potato, egg and carrot with canned peas, pickled gherkin and doktorskaya-"
           "style bologna under mayonnaise — the salad is mixed cold, nothing is lost",
           (I("bls:K110132", 200), I("bls:E111132", 100), I("bls:G620132", 60), I("bls:G760902", 100),
            I("bls:G890902", 100), I("bls:W236000", 150), I("ciqual:11054", 120)),
           cooked_yield=1.0, kcal_band=(160, 260), serving_g=150),
    Recipe("kurt", "Kurt", "Курт",
           "fooddb editorial: salted sour-milk curd strained and dried hard — quark 20 % with salt to ~30 % "
           "of the raw weight; the moisture is an assumption: kurt ranges from soft to stone-dry",
           (I("bls:M713300", 1000), I("ciqual:11017", 20)),
           cooked_yield=0.30, kcal_band=(280, 420), serving_g=50),
    Recipe("kumys", "Kumys", "Кумыс",
           "fooddb editorial: fermented mare's milk, modelled as mare's milk — fermentation moves part of the "
           "lactose to lactic acid and ~1–2 % alcohol that the model does not add; mass is nearly unchanged",
           (I("ciqual:19225", 1000),),
           cooked_yield=0.98, kcal_band=(30, 70), serving_g=250),
    Recipe("ayran", "Ayran", "Айран",
           "fooddb editorial: yogurt beaten with water and salt, ~3:2",
           (I("ciqual:19593", 600), I("ciqual:18066", 400), I("ciqual:11017", 4)),
           cooked_yield=1.0, kcal_band=(20, 45), serving_g=250),
    Recipe("baursak", "Baursak", "Баурсак",
           "fooddb editorial: deep-fried dough pillows — milk dough (flour, milk, egg, sugar) fried, taking up "
           "sunflower oil while moisture leaves",
           (I("bls:C214200", 300), I("bls:M111300", 150), I("bls:E111100", 25), I("bls:S111000", 15),
            I("ciqual:11017", 3), I("bls:Q320000", 60)),
           cooked_yield=0.82, kcal_band=(320, 450), serving_g=100),
    Recipe("lagman", "Lagman", "Лагман",
           "fooddb editorial: noodle soup — hand-pulled egg noodles under beef with pepper, carrot, onion, "
           "garlic and tomato paste fried in oil, water to the serving broth",
           (I("bls:E432000", 150), I("bls:U184100", 150), I("bls:G543100", 80), I("bls:R160000", 20),
            I("bls:G620100", 50), I("bls:G480100", 60), I("bls:G490100", 5), I("bls:Q320000", 20),
            I("ciqual:18066", 500)),
           cooked_yield=0.95, kcal_band=(70, 140), serving_g=350),
    Recipe("samsa", "Samsa", "Самса",
           "fooddb editorial: baked pastry — butter dough around minced lamb with onion and tail fat; baking "
           "loses ~20 % of the raw weight",
           (I("bls:C214200", 200), I("ciqual:18066", 90), I("bls:Q6A4000", 30), I("ciqual:11017", 7),
            I("bls:U807000", 150), I("bls:Q880000", 40), I("bls:G480100", 100)),
           cooked_yield=0.8, kcal_band=(240, 360), serving_g=150),
    Recipe("shashlik", "Shashlik, pork", "Шашлык из свинины",
           "fooddb editorial: pork neck marinated with onion and vinegar, grilled — the skewer loses fat and "
           "juice to ~62 % of the raw weight",
           (I("bls:U632100", 400), I("bls:G480100", 60), I("bls:R121000", 20), I("ciqual:11017", 6)),
           cooked_yield=0.62, kcal_band=(190, 340), serving_g=250),
    Recipe("blini", "Blini", "Блины",
           "fooddb editorial: thin milk pancakes — batter of flour, milk, egg, sugar and butter, fried; the "
           "pan loses ~20 % of the batter's weight",
           (I("bls:C214200", 150), I("bls:M111300", 300), I("bls:E111100", 50), I("bls:S111000", 15),
            I("bls:Q6A4000", 20), I("ciqual:11017", 2)),
           cooked_yield=0.8, kcal_band=(180, 290), serving_g=150),
    Recipe("grechka", "Buckwheat porridge with butter", "Гречка с маслом",
           "fooddb editorial: buckwheat groats boiled in twice their water with butter stirred in",
           (I("bls:C327000", 100), I("ciqual:18066", 220), I("bls:Q6A4000", 15), I("ciqual:11017", 2)),
           cooked_yield=0.98, kcal_band=(100, 160), serving_g=200),
    Recipe("tvorog", "Tvorog", "Творог",
           "fooddb editorial: tvorog is pressed harder than Speisequark, so whey leaves — 800 g quark 20 % "
           "+ 200 g quark 40 % pressed to 71 % of the raw weight lands on 9 % fat tvorog (GOST 31453): "
           "≈ P 16.8, F 9.0, C 4.1, ~169 kcal",
           (I("bls:M713300", 800), I("bls:M713500", 200)),
           cooked_yield=0.71, kcal_band=(140, 200), serving_g=200),
    Recipe("chebureki", "Chebureki", "Чебуреки",
           "fooddb editorial: deep-fried meat pasties — unleavened dough around minced lamb with onion, fried "
           "in sunflower oil",
           (I("bls:C214200", 200), I("ciqual:18066", 90), I("ciqual:11017", 5), I("bls:U807000", 150),
            I("bls:G480100", 80), I("bls:Q320000", 40)),
           cooked_yield=0.85, kcal_band=(220, 340), serving_g=150),
)


def registry_ref() -> str:
    """A short hash of the formulations: the `ref` a recipe run consumed."""
    raw = json.dumps([asdict(r) for r in RECIPES], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _choavl(values: dict[str, float]) -> dict[str, float]:
    """A record's values with carbohydrate on the CHOAVL basis: CHOCDF − FIBTG when only CHOCDF is stated."""
    if "CHOAVL" not in values and "CHOCDF" in values and "FIBTG" in values:
        v = dict(values)
        v["CHOAVL"] = max(v.pop("CHOCDF") - v["FIBTG"], 0.0)
        return v
    return values


def compute(recipe: Recipe, values: dict[str, dict[str, float]]) -> tuple[dict[str, float], dict[str, float]]:
    """Per-100 g values of the cooked dish, and the nutrients dropped for low coverage (nutrient → the share of
    the raw mix stating it). `values` maps each ingredient record to its per-100 g values."""
    by_record = {i.record: _choavl(values.get(i.record, {})) for i in recipe.ingredients}
    raw = sum(i.grams for i in recipe.ingredients)
    found, dropped = {}, {}
    for n in {n for v in by_record.values() for n in v}:
        coverage = sum(i.grams for i in recipe.ingredients if n in by_record[i.record]) / raw
        if coverage >= MIN_COVERAGE:
            v = sum(i.grams * by_record[i.record][n] for i in recipe.ingredients
                    if n in by_record[i.record]) / (raw * recipe.cooked_yield)
            found[n] = float(f"{v:.{DIGITS}g}")
        else:
            dropped[n] = coverage
    return found, dropped


def ingredient_sources(record_id: str) -> set[str]:
    """The sources a recipe record's values are computed from (e.g. {"fdc", "bls"})."""
    slug = record_id.removeprefix("recipe:").removesuffix(".ru")
    recipe = next((r for r in RECIPES if r.slug == slug), None)
    return {i.record.split(":", 1)[0] for i in recipe.ingredients} if recipe else set()


# The newest accepted value per nutrient of each record; a null row is a withdrawal the source made.
VALUES_SQL = """
select distinct on (food_id, nutrient) food_id, nutrient, value_per_100::float8 as value
from observation
where food_id = any(:ids) and status = 'accepted'
order by food_id, nutrient, observed_at desc, id desc
"""


def build(recipes: tuple[Recipe, ...] = RECIPES) -> dict:
    """Recompute the recipes from their ingredients' current accepted values and ingest what changed.
    Every computed value is pending, so a new or changed recipe is reviewed once before it serves."""
    ids = sorted({i.record for r in recipes for i in r.ingredients})
    with engine().connect() as conn:
        meta = {r["id"]: r for r in conn.execute(
            text("select id, name, licence from food where id = any(:ids)"), {"ids": ids}).mappings()}
        values: dict[str, dict[str, float]] = {i: {} for i in ids}
        for row in conn.execute(text(VALUES_SQL), {"ids": ids}).mappings():
            if row["value"] is not None:
                values.setdefault(row["food_id"], {})[row["nutrient"]] = row["value"]
    at = datetime.now(UTC)
    records = []
    for r in recipes:
        missing = [i.record for i in r.ingredients if not values.get(i.record)]
        if missing:
            continue  # an ingredient never loaded or still pending: the recipe is skipped, see report()
        licence = max((meta[i.record]["licence"] for i in r.ingredients),
                      key=lambda lic: _rank(lic))
        found, _dropped = compute(r, values)
        flags = [OUTLIER_FLAG] if r.kcal_band and not r.kcal_band[0] <= found.get("ENERC_KCAL", 0) <= r.kcal_band[1] else []
        for suffix, name, lang in (("", r.name_en, "en"), (".ru", r.name_ru, "ru")):
            records.append(ingest.Record(
                id=f"recipe:{r.slug}{suffix}", source=SOURCE, layer="core", licence=licence,
                name=name, lang=lang, serving_g=r.serving_g, values=found, observed_at=at,
                categories=["recipe:dish"], extra_flags=list(flags), review_all=True, group=r.slug))
    if not records:
        return {"recipes": 0, "skipped": len(recipes), "foods": 0, "observations": 0}
    foods, obs = ingest.run(SOURCE, registry_ref(), records)
    return {"recipes": len(records) // 2, "skipped": len(recipes) - len(records) // 2,
            "foods": foods, "observations": obs}


def _rank(licence: str) -> int:
    """The licence's place in resolve's restrictive order; an unknown one is the most restrictive."""
    from fooddb.resolve import LICENCES

    return LICENCES.index(licence) if licence in LICENCES else len(LICENCES)


def report(recipes: tuple[Recipe, ...] = RECIPES) -> str:
    """The readable review list: each recipe's formulation, citation, computed values, coverage drops and
    whether the computed kcal sits inside its plausible band."""
    ids = sorted({i.record for r in recipes for i in r.ingredients})
    with engine().connect() as conn:
        meta = {r["id"]: r for r in conn.execute(
            text("select id, name, licence, source from food where id = any(:ids)"), {"ids": ids}).mappings()}
        values: dict[str, dict[str, float]] = {i: {} for i in ids}
        for row in conn.execute(text(VALUES_SQL), {"ids": ids}).mappings():
            if row["value"] is not None:
                values.setdefault(row["food_id"], {})[row["nutrient"]] = row["value"]
    lines = []
    for r in recipes:
        raw = sum(i.grams for i in r.ingredients)
        lines.append(f"{r.slug}: {r.name_en} / {r.name_ru}  (recipe:{r.slug}, recipe:{r.slug}.ru)")
        lines.append(f"  citation: {r.citation}")
        lines.append(f"  cooked yield {r.cooked_yield}: {raw:g} g raw → {raw * r.cooked_yield:g} g")
        for i in r.ingredients:
            m = meta.get(i.record)
            lines.append(f"    {i.grams:>8g} g  {i.record:<18} {m['name'] if m else 'MISSING'}")
        missing = [i.record for i in r.ingredients if not values.get(i.record)]
        if missing:
            lines.append(f"  NOT COMPUTABLE — no accepted values for {', '.join(missing)}")
            continue
        found, dropped = compute(r, values)
        kcal = found.get("ENERC_KCAL")
        band = "" if kcal is None or not r.kcal_band else (
            "OK" if r.kcal_band[0] <= kcal <= r.kcal_band[1] else f"OUTSIDE {r.kcal_band[0]:g}–{r.kcal_band[1]:g}")
        lines.append(f"  kcal band: {band}")
        lines.append("  computed per 100 g: " + ", ".join(f"{n} {v:.4g}" for n, v in sorted(found.items())))
        if dropped:
            lines.append("  dropped, coverage <90 %: " + ", ".join(f"{n} {c:.0%}" for n, c in sorted(dropped.items())))
        lines.append("")
    return "\n".join(lines)
