"""Recipes: dishes computed from ingredient records — their values are never typed in.

Each recipe names the ingredient records of the composition tables (fdc, bls, ciqual, cofid, …)
with their grams in the raw mix, a cooked yield (the cooked dish's weight divided by the raw mix;
a water-loss factor below 1, a gain above) and the citation of its formulation. `compute` weighs
each ingredient's newest accepted per-100 g values into the cooked dish's; `build` stores them
through the normal ingest path with `review_all`, so every value waits in the review queue and a
recipe stays invisible until a person accepts it once. The same build sweeps after itself: a
record's older pending rows are rejected once a newer observation of the nutrient exists, and a
record whose slug left RECIPES is retired — queue rejected, served nutrients withdrawn — so nothing
stays pending or orphaned.

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

from loguru import logger
from sqlalchemy import text

from fooddb import ingest
from fooddb.db import engine

SOURCE = "recipe"
REVIEWER = "fooddb:recipes"  # the by-line the build's own sweep writes on the rows it decides
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
 # ── Soups ──
 Recipe("solyanka", "Solyanka, meat", "Солянка мясная",
        "fooddb editorial: mixed-meat solyanka — boiled beef with smoked sausage and bologna, onion, "
        "pickled gherkins, olives and tomato paste on broth, finished with lemon and sour cream; "
        "~5 % of the pot evaporates",
        (I("bls:U184100", 120), I("ciqual:30102", 60), I("bls:W236000", 60), I("bls:G480100", 50),
         I("bls:G890902", 60), I("bls:H510802", 30), I("bls:R160000", 30), I("bls:F601600", 10),
         I("bls:M172700", 30), I("bls:Q320000", 15), I("ciqual:18066", 550), I("ciqual:11017", 6)),
        cooked_yield=0.95, kcal_band=(55, 110), serving_g=300),
 Recipe("okroshka", "Okroshka on kefir", "Окрошка на кефире",
        "fooddb editorial: cold soup — kefir thinned with water, boiled potato and egg, cucumber, "
        "bologna and dill; mixed cold, nothing is lost",
        (I("bls:M130300", 500), I("ciqual:18066", 300), I("bls:K110132", 150), I("bls:E111132", 60),
         I("bls:G520100", 120), I("bls:W236000", 80), I("ciqual:11093", 8), I("bls:M172700", 40),
         I("ciqual:11017", 5)),
        cooked_yield=1.0, kcal_band=(35, 70), serving_g=300),
 Recipe("rassolnik", "Rassolnik", "Рассольник",
        "fooddb editorial: pickle-barley soup on beef — boiled pearl barley, potato, carrot and onion "
        "with pickled gherkins, simmered; ~5 % of the pot evaporates",
        (I("bls:U184100", 100), I("bls:C148000", 50), I("bls:K110100", 150), I("bls:G620100", 40),
         I("bls:G480100", 50), I("bls:G890902", 100), I("ciqual:18066", 600), I("bls:Q320000", 10),
         I("ciqual:11017", 6), I("bls:M172700", 30)),
        cooked_yield=0.95, kcal_band=(35, 70), serving_g=300),
 Recipe("svekolnik", "Svekolnik, cold beet soup", "Свекольник",
        "fooddb editorial: cold beet soup — boiled beet and its broth cooled with kefir, cucumber, "
        "egg and dill; mixed cold",
        (I("bls:G613132", 200), I("ciqual:18066", 400), I("bls:M130300", 300), I("bls:G520100", 100),
         I("bls:E111132", 60), I("ciqual:11093", 8), I("bls:M172700", 40), I("ciqual:11017", 5)),
        cooked_yield=1.0, kcal_band=(25, 55), serving_g=300),
 Recipe("zeleny-borscht", "Green borscht (sorrel soup)", "Зелёный борщ",
        "fooddb editorial: sorrel soup — sorrel, potato and carrot on beef broth, served with egg "
        "and sour cream; ~5 % evaporates",
        (I("bls:G263100", 80), I("bls:K110100", 150), I("bls:G620100", 40), I("bls:G480100", 40),
         I("bls:U184100", 80), I("ciqual:18066", 500), I("bls:E111132", 50), I("bls:M172700", 40),
         I("ciqual:11017", 6)),
        cooked_yield=0.95, kcal_band=(30, 65), serving_g=300),
 Recipe("kharcho", "Kharcho", "Харчо",
        "fooddb editorial: Georgian beef-walnut soup — beef, rice, walnuts, tomato and garlic with "
        "coriander, simmered; ~5 % evaporates",
        (I("bls:U184100", 200), I("bls:C352000", 60), I("bls:H120100", 40), I("bls:R160000", 30),
         I("bls:G561100", 100), I("bls:G480100", 50), I("bls:G490100", 8), I("ciqual:18066", 550),
         I("fdc:170921", 3), I("ciqual:11017", 6)),
        cooked_yield=0.95, kcal_band=(45, 90), serving_g=300),
 Recipe("shurpa", "Shurpa", "Шурпа",
        "fooddb editorial: Central Asian lamb soup — lamb with potato, carrot, onion and pepper in a "
        "clear broth; ~5 % evaporates",
        (I("bls:U807000", 200), I("bls:K110100", 150), I("bls:G620100", 80), I("bls:G480100", 60),
         I("bls:G543100", 60), I("ciqual:18066", 550), I("ciqual:11017", 7)),
        cooked_yield=0.95, kcal_band=(35, 80), serving_g=350),
 Recipe("mampar", "Mampar", "Мампар",
        "fooddb editorial: Central Asian soup — small rolled dough squares in beef broth with potato, "
        "carrot and onion; ~5 % evaporates",
        (I("bls:U184100", 150), I("bls:C214200", 100), I("ciqual:18066", 560), I("bls:K110100", 100),
         I("bls:G620100", 50), I("bls:G480100", 50), I("ciqual:11017", 6)),
        cooked_yield=0.95, kcal_band=(40, 80), serving_g=350),
 Recipe("kuksi", "Kuksi", "Кукси",
        "fooddb editorial: Korean-Kazakh cold noodle soup — egg noodles in cold beef broth with "
        "cucumber, egg and vinegar; the noodles take up water, so the serving weighs more than the mix",
        (I("bls:E432000", 120), I("bls:U184100", 80), I("ciqual:18066", 450), I("bls:G520100", 80),
         I("bls:E111132", 40), I("bls:R121000", 10), I("ciqual:11017", 5), I("bls:S111000", 5)),
        cooked_yield=1.1, kcal_band=(40, 75), serving_g=350),
 # ── Dumplings and filled pastry ──
 Recipe("khinkali", "Khinkali", "Хинкали",
        "fooddb editorial: Georgian broth dumplings — unleavened dough around spiced beef-pork mince "
        "with onion and a little water inside; boiled, dough takes up a little water",
        (I("bls:C214200", 200), I("ciqual:18066", 120), I("ciqual:11017", 5), I("bls:U050100", 300),
         I("bls:G480100", 60), I("ciqual:11015", 2)),
        cooked_yield=1.05, kcal_band=(160, 260), serving_g=250),
 Recipe("vareniki-tvorog", "Vareniki, tvorog filling", "Вареники с творогом",
        "fooddb editorial: boiled dumplings — unleavened dough around tvorog with sugar and egg yolk",
        (I("bls:C214200", 200), I("ciqual:18066", 80), I("bls:E111100", 25), I("ciqual:11017", 5),
         I("bls:M713300", 280), I("bls:S111000", 30), I("bls:E112100", 15)),
        cooked_yield=1.02, kcal_band=(150, 230), serving_g=250),
 Recipe("vareniki-vishnya", "Vareniki, sour cherry filling", "Вареники с вишней",
        "fooddb editorial: boiled dumplings — unleavened dough around sour cherries with sugar",
        (I("bls:C214200", 200), I("ciqual:18066", 80), I("bls:E111100", 25), I("ciqual:11017", 5),
         I("bls:F212100", 280), I("bls:S111000", 40)),
        cooked_yield=1.02, kcal_band=(130, 200), serving_g=250),
 Recipe("manty-tykva", "Manty, pumpkin filling", "Манты с тыквой",
        "fooddb editorial: steamed dumplings — unleavened dough around raw pumpkin with onion and "
        "tail fat; steaming loses ~10 %",
        (I("bls:C214200", 200), I("ciqual:18066", 80), I("ciqual:11017", 7), I("bls:G581100", 300),
         I("bls:G480100", 80), I("bls:Q880000", 40)),
        cooked_yield=0.9, kcal_band=(110, 190), serving_g=250),
 Recipe("manty-kartoshka", "Manty, potato filling", "Манты с картошкой",
        "fooddb editorial: steamed dumplings — unleavened dough around raw potato with onion and "
        "tail fat; steaming loses ~10 %",
        (I("bls:C214200", 200), I("ciqual:18066", 80), I("ciqual:11017", 7), I("bls:K110100", 300),
         I("bls:G480100", 80), I("bls:Q880000", 40)),
        cooked_yield=0.9, kcal_band=(130, 210), serving_g=250),
 Recipe("pyanse", "Pyanse (steamed meat bun)", "Пянсе",
        "fooddb editorial: Korean-Kazakh steamed bun — yeast dough around pork mince with cabbage "
        "and onion; steaming loses ~5 %",
        (I("bls:C214200", 220), I("ciqual:18066", 120), I("bls:R459000", 5), I("bls:S111000", 5),
         I("ciqual:11017", 5), I("bls:U020100", 180), I("bls:G342100", 120), I("bls:G480100", 50)),
        cooked_yield=0.95, kcal_band=(170, 260), serving_g=200),
 Recipe("khoshan", "Khoshan", "Хошан",
        "fooddb editorial: Kazakh fried dumplings — yeasted flat cakes of dough around pork mince "
        "with onion, deep-fried; the frying drives off water and the dough takes up oil",
        (I("bls:C214200", 200), I("ciqual:18066", 110), I("bls:R459000", 4), I("ciqual:11017", 5),
         I("bls:U020100", 180), I("bls:G480100", 60), I("bls:Q320000", 40)),
        cooked_yield=0.85, kcal_band=(220, 330), serving_g=200),
 Recipe("pirozhki-potato", "Pirozhki, potato filling", "Пирожки с картошкой",
        "fooddb editorial: baked yeast-dough pies with mashed potato and fried onion; baking loses "
        "~15 % of the raw weight",
        (I("bls:C214200", 250), I("bls:M111300", 120), I("bls:E111100", 25), I("bls:R459000", 5),
         I("bls:S111000", 10), I("ciqual:11017", 5), I("bls:Q6A4000", 20), I("bls:K110132", 250),
         I("bls:G480100", 60), I("bls:Q320000", 15)),
        cooked_yield=0.85, kcal_band=(200, 290), serving_g=150),
 Recipe("pirozhki-cabbage", "Pirozhki, cabbage filling", "Пирожки с капустой",
        "fooddb editorial: baked yeast-dough pies with stewed cabbage and egg; baking loses ~15 %",
        (I("bls:C214200", 250), I("bls:M111300", 120), I("bls:E111100", 25), I("bls:R459000", 5),
         I("bls:S111000", 10), I("ciqual:11017", 5), I("bls:Q6A4000", 20), I("bls:G342100", 250),
         I("bls:Q320000", 20), I("bls:E111132", 40)),
        cooked_yield=0.85, kcal_band=(170, 260), serving_g=150),
 Recipe("pirog-kapusta", "Cabbage pie", "Пирог с капустой",
        "fooddb editorial: baked yeast pie — a thinner dough shell around more stewed cabbage than "
        "pirozhki, with boiled egg; ~15 % lost in the oven",
        (I("bls:C214200", 200), I("bls:M111300", 100), I("bls:E111100", 25), I("bls:R459000", 5),
         I("bls:S111000", 8), I("ciqual:11017", 5), I("bls:Q6A4000", 20), I("bls:G342100", 350),
         I("bls:Q320000", 25), I("bls:E111132", 50)),
        cooked_yield=0.85, kcal_band=(150, 240), serving_g=150),
 Recipe("khachapuri", "Khachapuri, imeruli", "Хачапури",
        "fooddb editorial: Imeretian khachapuri — yeast-dough flatbread around a mild brined-cheese "
        "mix; imeruli cheese is not in the tables, so the standing model is feta lightened with "
        "mozzarella; baking loses ~15 %",
        (I("bls:C214200", 250), I("bls:M111300", 120), I("bls:R459000", 5), I("ciqual:11017", 5),
         I("bls:M012200", 180), I("bls:M032100", 120), I("bls:Q6A4000", 15)),
        cooked_yield=0.85, kcal_band=(230, 330), serving_g=200),
 Recipe("khachapuri-adjaruli", "Khachapuri adjaruli", "Хачапури по-аджарски",
        "fooddb editorial: Adjarian khachapuri — the dough boat holds the same brined-cheese mix "
        "with a raw egg and butter on top; baking loses ~12 %",
        (I("bls:C214200", 220), I("bls:M111300", 100), I("bls:R459000", 5), I("ciqual:11017", 5),
         I("bls:M012200", 160), I("bls:M032100", 100), I("bls:E111100", 50), I("bls:Q6A4000", 20)),
        cooked_yield=0.88, kcal_band=(230, 330), serving_g=250),
 Recipe("kiev-cutlet", "Chicken Kiev", "Котлета по-киевски",
        "fooddb editorial: chicken breast wrapped around butter, breaded in flour, egg and crumbs, "
        "deep-fried; frying loses water but takes up oil",
        (I("bls:V416100", 300), I("bls:Q6A4000", 80), I("bls:C214200", 40), I("bls:E111100", 50),
         I("bls:B821000", 60), I("bls:Q320000", 60), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(260, 390), serving_g=200),
 Recipe("zrazy", "Zrazy, potato dough with meat", "Зразы",
        "fooddb editorial: potato-dough cutlets around fried mince with onion; ~15 % lost in the pan",
        (I("bls:K110132", 350), I("bls:C214200", 60), I("bls:E111100", 25), I("ciqual:11017", 5),
         I("bls:U050100", 180), I("bls:G480100", 60), I("bls:Q320000", 30)),
        cooked_yield=0.85, kcal_band=(130, 210), serving_g=200),
 Recipe("blini-myaso", "Blini, meat filling", "Блины с мясом",
        "fooddb editorial: thin milk pancakes around fried beef mince with onion; ~18 % of the raw "
        "weight leaves the pan",
        (I("bls:C214200", 120), I("bls:M111300", 240), I("bls:E111100", 40), I("bls:S111000", 10),
         I("ciqual:11017", 3), I("bls:U010100", 200), I("bls:G480100", 50), I("bls:Q320000", 25)),
        cooked_yield=0.82, kcal_band=(170, 270), serving_g=200),
 Recipe("blini-tvorog", "Blini, tvorog filling", "Блины с творогом",
        "fooddb editorial: thin milk pancakes around sweetened tvorog; ~15 % lost in the pan",
        (I("bls:C214200", 120), I("bls:M111300", 240), I("bls:E111100", 40), I("bls:S111000", 15),
         I("ciqual:11017", 3), I("bls:M713300", 250), I("bls:E112100", 15), I("bls:Q320000", 15)),
        cooked_yield=0.85, kcal_band=(170, 260), serving_g=200),
 Recipe("pelmeni-zharenye", "Pelmeni, fried", "Пельмени жареные",
        "fooddb editorial: boiled dumplings fried in oil — the pelmeni formulation plus a frying "
        "step: ~10 % of the boiled weight leaves and oil is taken up",
        (I("bls:C214200", 200), I("ciqual:18066", 80), I("bls:E111100", 25), I("ciqual:11017", 7),
         I("bls:U050100", 250), I("bls:G480100", 60), I("bls:Q320000", 40)),
        cooked_yield=0.9, kcal_band=(200, 300), serving_g=200),
 # ── Mains and sides ──
 Recipe("makarony-po-flotski", "Navy-style pasta with minced meat", "Макароны по-флотски",
        "fooddb editorial: boiled pasta tossed with beef-pork mince fried with onion and a little "
        "tomato; the pasta takes up water on boiling",
        (I("bls:E401000", 150), I("bls:U050100", 200), I("bls:G480100", 60), I("bls:Q320000", 15),
         I("bls:R160000", 15), I("ciqual:11017", 5), I("ciqual:18066", 150)),
        cooked_yield=1.05, kcal_band=(160, 250), serving_g=300),
 Recipe("grechka-myaso", "Buckwheat with meat", "Гречка с мясом",
        "fooddb editorial: buckwheat porridge with beef stewed with onion and carrot — "
        "merchant-style, meat folded into the groats",
        (I("bls:C327000", 150), I("ciqual:18066", 300), I("bls:U184100", 150), I("bls:G480100", 50),
         I("bls:G620100", 50), I("bls:Q6A4000", 15), I("ciqual:11017", 4)),
        cooked_yield=0.98, kcal_band=(110, 180), serving_g=250),
 Recipe("azu", "Azu", "Азу",
        "fooddb editorial: Tatar stew — beef with pickled gherkins, tomato, potato and onion in a "
        "little broth; ~10 % evaporates",
        (I("bls:U151100", 200), I("bls:G890902", 60), I("bls:R160000", 25), I("bls:K110100", 150),
         I("bls:G480100", 60), I("ciqual:18066", 120), I("bls:Q320000", 15), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(80, 140), serving_g=300),
 Recipe("myaso-frantsuzski", "Meat French-style", "Мясо по-французски",
        "fooddb editorial: pork slices baked under onion, tomato, mayonnaise and cheese; ~15 % of "
        "the raw weight leaves",
        (I("bls:U632100", 250), I("bls:G480100", 80), I("bls:G561100", 100), I("ciqual:11054", 60),
         I("bls:M303600", 80), I("ciqual:11017", 4)),
        cooked_yield=0.85, kcal_band=(180, 300), serving_g=200),
 Recipe("pure-kotleta", "Mashed potato with meat cutlet", "Пюре с котлетой",
        "fooddb editorial: boiled potato mashed with milk and butter next to a fried mixed-mince "
        "cutlet — the plate, both halves weighed",
        (I("bls:K110132", 250), I("bls:M111300", 60), I("bls:Q6A4000", 15), I("ciqual:11017", 4),
         I("bls:U050100", 150), I("bls:G480100", 30), I("bls:E111100", 15), I("bls:C214200", 15),
         I("bls:Q320000", 15)),
        cooked_yield=0.95, kcal_band=(130, 200), serving_g=300),
 Recipe("kuyrdak", "Kuyrdak", "Куырдак",
        "fooddb editorial: Central Asian offal fry — liver, kidney and heart with potato and onion "
        "fried in tail fat; ~15 % lost",
        (I("bls:U080100", 100), I("bls:V571100", 80), I("bls:V511100", 80), I("bls:K110100", 200),
         I("bls:G480100", 80), I("bls:Q880000", 40), I("ciqual:11017", 6)),
        cooked_yield=0.85, kcal_band=(140, 230), serving_g=250),
 Recipe("dimlama", "Dimlama", "Димляма",
        "fooddb editorial: layered stew — lamb with potato, carrot, cabbage, pepper and onion "
        "steamed in their own juice; ~10 % lost",
        (I("bls:U807000", 180), I("bls:K110100", 150), I("bls:G620100", 80), I("bls:G342100", 100),
         I("bls:G543100", 60), I("bls:G480100", 60), I("ciqual:18066", 100), I("ciqual:11017", 6)),
        cooked_yield=0.9, kcal_band=(55, 120), serving_g=300),
 Recipe("kazan-kebab", "Kazan kebab", "Казан-кебаб",
        "fooddb editorial: lamb and potatoes fried together in the kazan with onion; the frying "
        "loses ~20 % to steam and rendered fat",
        (I("bls:U807000", 250), I("bls:K110100", 300), I("bls:G480100", 80), I("bls:Q880000", 30),
         I("ciqual:11017", 6)),
        cooked_yield=0.8, kcal_band=(140, 230), serving_g=250),
 Recipe("syrne", "Syrne", "Сырне",
        "fooddb editorial: Kazakh kazan braise — lamb with potato, carrot and onion steamed under a "
        "lid; ~15 % lost",
        (I("bls:U807000", 220), I("bls:K110100", 200), I("bls:G620100", 80), I("bls:G480100", 80),
         I("ciqual:18066", 80), I("ciqual:11017", 6)),
        cooked_yield=0.85, kcal_band=(75, 150), serving_g=300),
 Recipe("ganfan", "Ganfan", "Ганфан",
        "fooddb editorial: Dungan rice plate — boiled rice under beef with pepper, carrot and onion "
        "fried and sauced",
        (I("bls:C352000", 100), I("ciqual:18066", 220), I("bls:U184100", 150), I("bls:G543100", 60),
         I("bls:G620100", 50), I("bls:G480100", 50), I("bls:R160000", 15), I("bls:Q320000", 15),
         I("bls:R143000", 10), I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(110, 170), serving_g=300),
 Recipe("shashlik-kuritsa", "Shashlik, chicken", "Шашлык из курицы",
        "fooddb editorial: chicken thigh marinated with onion and vinegar, grilled — the skewer "
        "loses juice to ~68 % of the raw weight",
        (I("bls:V4A5100", 400), I("bls:G480100", 60), I("bls:R121000", 15), I("ciqual:11017", 6)),
        cooked_yield=0.68, kcal_band=(170, 290), serving_g=200),
 Recipe("lyulya-kebab", "Lyulya kebab", "Люля-кебаб",
        "fooddb editorial: minced lamb with tail fat and onion, grilled on skewers — fat drips off "
        "to ~70 % of the raw weight",
        (I("bls:U807000", 300), I("bls:Q880000", 80), I("bls:G480100", 60), I("ciqual:11017", 6),
         I("fdc:170923", 3)),
        cooked_yield=0.7, kcal_band=(200, 320), serving_g=200),
 Recipe("chakhokhbili", "Chakhokhbili", "Чахохбили",
        "fooddb editorial: Georgian chicken stew — chicken braised down with tomato and onion, "
        "barely any water; ~15 % lost",
        (I("bls:V413000", 300), I("bls:G561100", 300), I("bls:G480100", 150), I("bls:Q320000", 15),
         I("bls:R160000", 20), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(90, 150), serving_g=300),
 Recipe("lobio", "Lobio", "Лобио",
        "fooddb editorial: Georgian red-bean stew — boiled kidney beans with onion, tomato, walnut, "
        "garlic and coriander",
        (I("bls:H742100", 250), I("ciqual:18066", 500), I("bls:G480100", 80), I("bls:G561100", 100),
         I("bls:H120100", 40), I("bls:G490100", 8), I("fdc:170921", 4), I("bls:Q320000", 15),
         I("ciqual:11017", 6)),
        cooked_yield=0.95, kcal_band=(90, 145), serving_g=250),
 Recipe("lecho", "Lecho", "Лечо",
        "fooddb editorial: pepper stew — sweet pepper and tomato stewed with onion; ~10 % evaporates",
        (I("bls:G543100", 400), I("bls:G561100", 300), I("bls:G480100", 80), I("bls:Q320000", 20),
         I("bls:S111000", 10), I("ciqual:11017", 6)),
        cooked_yield=0.9, kcal_band=(35, 70), serving_g=250),
 Recipe("ris-ovoshchi", "Rice with vegetables", "Рис с овощами",
        "fooddb editorial: boiled rice folded with carrot, onion, pepper and peas fried in oil",
        (I("bls:C352000", 120), I("ciqual:18066", 260), I("bls:G620100", 60), I("bls:G480100", 50),
         I("bls:G543100", 60), I("bls:G760132", 50), I("bls:Q320000", 15), I("ciqual:11017", 4)),
        cooked_yield=0.98, kcal_band=(100, 150), serving_g=250),
 Recipe("tykvennaya-kasha", "Pumpkin-millet porridge", "Тыквенная каша",
        "fooddb editorial: millet boiled with pumpkin in milk, finished with butter and a little "
        "sugar",
        (I("bls:C332000", 100), I("bls:G581100", 200), I("bls:M111300", 300), I("bls:Q6A4000", 15),
         I("bls:S111000", 15), I("ciqual:11017", 2)),
        cooked_yield=0.98, kcal_band=(90, 140), serving_g=250),
 # ── Salads, preserves, sauces ──
 Recipe("vinegret", "Vinegret (beet salad)", "Винегрет",
        "fooddb editorial: boiled beet, potato and carrot diced with sauerkraut, pickles and onion "
        "under sunflower oil; mixed cold",
        (I("bls:G613132", 150), I("bls:K110132", 120), I("bls:G620132", 80), I("bls:G345100", 80),
         I("bls:G890902", 60), I("bls:G480100", 40), I("bls:Q320000", 30), I("ciqual:11017", 3)),
        cooked_yield=1.0, kcal_band=(70, 120), serving_g=150),
 Recipe("selyodka-pod-shuboy", "Herring under a fur coat", "Селёдка под шубой",
        "fooddb editorial: layered salad — salted herring under boiled potato, carrot and beet "
        "grated with egg and onion, each layer under mayonnaise; mixed cold",
        (I("bls:T102400", 150), I("bls:K110132", 150), I("bls:G620132", 80), I("bls:G613132", 150),
         I("bls:E111132", 60), I("bls:G480100", 40), I("ciqual:11054", 120)),
        cooked_yield=1.0, kcal_band=(150, 240), serving_g=150),
 Recipe("mimoza", "Mimosa salad", "Салат «Мимоза»",
        "fooddb editorial: layered salad — canned fish with boiled potato, carrot and egg under "
        "mayonnaise; mixed cold",
        (I("bls:T121702", 150), I("bls:K110132", 150), I("bls:G620132", 80), I("bls:E111132", 100),
         I("bls:G480100", 30), I("ciqual:11054", 100)),
        cooked_yield=1.0, kcal_band=(170, 260), serving_g=150),
 Recipe("morkovcha", "Korean-style carrot salad", "Морковь по-корейски",
        "fooddb editorial: julienned carrot salted, doused with hot oil, with garlic, vinegar and "
        "sugar; mixed cold, nothing is lost",
        (I("bls:G620100", 400), I("bls:Q320000", 60), I("bls:R121000", 20), I("bls:S111000", 15),
         I("bls:G490100", 10), I("fdc:170932", 2), I("ciqual:11017", 5)),
        cooked_yield=1.0, kcal_band=(100, 165), serving_g=150),
 Recipe("ikra-baklazhan", "Eggplant caviar", "Баклажанная икра",
        "fooddb editorial: eggplant baked and stewed down with tomato, pepper, onion and carrot; "
        "~15 % evaporates",
        (I("ciqual:20053", 400), I("bls:G561100", 200), I("bls:G543100", 150), I("bls:G480100", 80),
         I("bls:G620100", 80), I("bls:Q320000", 40), I("ciqual:11017", 6), I("bls:G490100", 5)),
        cooked_yield=0.85, kcal_band=(50, 90), serving_g=150),
 Recipe("ikra-kabachok", "Zucchini caviar", "Кабачковая икра",
        "fooddb editorial: zucchini stewed down with tomato paste, carrot and onion; ~20 % "
        "evaporates",
        (I("ciqual:20020", 500), I("bls:R160000", 40), I("bls:G561100", 100), I("bls:G620100", 100),
         I("bls:G480100", 80), I("bls:Q320000", 40), I("ciqual:11017", 6), I("bls:S111000", 8)),
        cooked_yield=0.8, kcal_band=(45, 95), serving_g=150),
 Recipe("adjika", "Adjika", "Аджика",
        "fooddb editorial: Abkhazian-style red adjika — sweet and hot peppers ground with garlic "
        "and salt; a raw paste, nothing is lost",
        (I("bls:G543100", 300), I("fdc:170106", 100), I("bls:G490100", 60), I("bls:Q320000", 20),
         I("ciqual:11017", 20)),
        cooked_yield=1.0, kcal_band=(60, 110), serving_g=30),
 Recipe("tkemali", "Tkemali sauce", "Ткемали",
        "fooddb editorial: Georgian sour-plum sauce — plums boiled down with garlic, dill, "
        "coriander and chili; ~20 % evaporates",
        (I("bls:F220100", 400), I("bls:G490100", 15), I("ciqual:11093", 10), I("fdc:169997", 10),
         I("fdc:170106", 10), I("ciqual:11017", 8), I("bls:S111000", 15)),
        cooked_yield=0.8, kcal_band=(50, 95), serving_g=30),
 # ── Dairy / drinks / sweets ──
 Recipe("toplenoe-moloko", "Baked milk (toplenoe moloko)", "Топлёное молоко",
        "fooddb editorial: milk held just below simmer until it creams — ~5 % of the water leaves",
        (I("bls:M111300", 1000),),
        cooked_yield=0.95, kcal_band=(60, 70), serving_g=250),
 Recipe("ryazhenka", "Ryazhenka", "Ряженка",
        "fooddb editorial: baked milk soured — modelled as milk fermented and set; fermentation "
        "moves lactose to lactic acid, mass nearly unchanged",
        (I("bls:M111300", 1000),),
        cooked_yield=0.98, kcal_band=(50, 70), serving_g=250),
 Recipe("syrok-glazirovanny", "Glazed curd cheese bar", "Сырок глазированный",
        "fooddb editorial: sweetened pressed curd with butter, coated in chocolate glaze — "
        "tvorog mixed with sugar and butter, dipped in dark chocolate",
        (I("bls:M713500", 250), I("bls:S111000", 70), I("bls:Q6A4000", 90),
         I("bls:M181400", 40), I("bls:S570000", 80)),
        cooked_yield=1.0, kcal_band=(340, 460), serving_g=45),
 Recipe("irimshik", "Irimshik (dried curd cheese)", "Ирімшік",
        "fooddb editorial: Kazakh sweet dried curd — quark boiled so it curdles, pressed and dried "
        "to ~45 % of the raw weight; softer and sweeter than kurt",
        (I("bls:M713500", 1000), I("bls:S111000", 40)),
        cooked_yield=0.45, kcal_band=(300, 430), serving_g=50),
 Recipe("kvass", "Kvass", "Квас",
        "fooddb editorial: rye bread fermented with water, sugar and yeast — the mash is strained, "
        "so only the liquid serves; fermentation burns part of the sugar and the bread solids leave",
        (I("bls:B221000", 120), I("ciqual:18066", 1000), I("bls:S111000", 40), I("bls:R459000", 3)),
        cooked_yield=0.9, kcal_band=(20, 45), serving_g=250),
 Recipe("kompot", "Kompot", "Компот",
        "fooddb editorial: fruit drink — apples and sour cherries simmered with sugar; the fruit is "
        "left in, ~5 % evaporates",
        (I("bls:F110100", 200), I("bls:F212100", 150), I("bls:S111000", 80), I("ciqual:18066", 1000)),
        cooked_yield=0.98, kcal_band=(30, 60), serving_g=250),
 Recipe("medovik", "Medovik (honey layer cake)", "Медовик",
        "fooddb editorial: honey layers (honey, sugar, butter, egg, flour) sandwiched with sour-"
        "cream cream; baking dries ~15 %, the cream adds back",
        (I("bls:C214200", 180), I("bls:S111000", 120), I("bls:S121000", 60), I("bls:Q6A4000", 60),
         I("bls:E111100", 50), I("bls:M172700", 200), I("ciqual:11017", 2)),
        cooked_yield=0.9, kcal_band=(280, 400), serving_g=100),
 Recipe("kartoshka-pirozhnoe", "Kartoshka pastry", "Пирожное «картошка»",
        "fooddb editorial: crumbled sponge worked with butter, condensed milk and cocoa, set cold",
        (I("bls:D085000", 300), I("bls:Q6A4000", 100), I("bls:M181400", 120), I("bls:S711000", 15)),
        cooked_yield=1.0, kcal_band=(380, 470), serving_g=60),
 Recipe("nishalda", "Nishalda", "Нишалда",
        "fooddb editorial: whipped egg whites beaten with hot sugar syrup to a cream — nothing "
        "cooked, the syrup dries in",
        (I("bls:E113100", 200), I("bls:S111000", 300)),
        cooked_yield=1.0, kcal_band=(230, 300), serving_g=40),
 Recipe("zhent", "Zhent", "Жент",
        "fooddb editorial: Kazakh millet sweet — roasted millet ground with butter, sugar and "
        "pressed curd, set cold",
        (I("bls:C333100", 250), I("bls:Q6A4000", 100), I("bls:S111000", 100), I("bls:M713300", 150)),
        cooked_yield=1.0, kcal_band=(330, 450), serving_g=50),
 Recipe("nauryz-kozhe", "Nauryz kozhe", "Наурыз көже",
        "fooddb editorial: Kazakh festival soup — boiled meat with millet in broth finished with "
        "fermented milk; modelled as meat, broth, millet and sour milk",
        (I("bls:U184100", 150), I("ciqual:18066", 400), I("bls:C332000", 60), I("bls:M130300", 200),
         I("bls:G480100", 40), I("ciqual:11017", 5)),
        cooked_yield=0.98, kcal_band=(50, 90), serving_g=300),
 Recipe("chak-chak", "Chak-chak", "Чак-чак",
        "fooddb editorial: Tatar sweet — small dough pieces deep-fried and bound with honey syrup; "
        "frying drives off ~15 %",
        (I("bls:C214200", 200), I("bls:M111300", 80), I("bls:E111100", 50), I("ciqual:11017", 2),
         I("bls:Q320000", 50), I("bls:S111000", 40), I("bls:S121000", 60)),
        cooked_yield=0.85, kcal_band=(380, 480), serving_g=50),
 Recipe("khvorost", "Khvorost", "Хворост",
        "fooddb editorial: fried pastry twists — thin dough of flour, egg, milk and sugar, deep-"
        "fried; ~10 % water out, oil in",
        (I("bls:C214200", 200), I("bls:E111100", 40), I("bls:M111300", 60), I("bls:S111000", 15),
         I("ciqual:11017", 2), I("bls:Q320000", 50)),
        cooked_yield=0.85, kcal_band=(400, 520), serving_g=50),
 Recipe("shelpek", "Shelpek", "Шелепек",
        "fooddb editorial: Kazakh fried flatbread — yeasted milk dough rolled thin, deep-fried; "
        "~15 % out, oil in",
        (I("bls:C214200", 250), I("bls:M111300", 120), I("bls:R459000", 4), I("bls:S111000", 5),
         I("ciqual:11017", 4), I("bls:Q320000", 40)),
        cooked_yield=0.85, kcal_band=(290, 400), serving_g=100),
 Recipe("bulochka-mak", "Poppy-seed bun", "Булочка с маком",
        "fooddb editorial: sweet yeast bun rolled around poppy seeds ground with sugar; baking "
        "loses ~12 %",
        (I("bls:C214200", 220), I("bls:M111300", 100), I("bls:E111100", 30), I("bls:S111000", 40),
         I("bls:Q6A4000", 30), I("bls:R459000", 5), I("bls:H450400", 60), I("ciqual:11017", 3)),
        cooked_yield=0.88, kcal_band=(300, 390), serving_g=80),
 # ── International, en/es-covered gaps ──
 Recipe("full-english", "Full English breakfast", "Полный английский завтрак",
        "fooddb editorial: the plate — fried egg, grilled bacon and pork sausage, baked beans in "
        "tomato sauce, fried tomato and mushroom, toast with butter",
        (I("bls:E111182", 60), I("bls:W415072", 40), I("fdc:172939", 60), I("ciqual:20194", 80),
         I("bls:G561100", 60), I("bls:K701182", 30), I("bls:B314072", 35), I("bls:Q6A4000", 8)),
        cooked_yield=1.0, kcal_band=(170, 260), serving_g=370),
 Recipe("bangers-mash", "Bangers and mash", "Сосиски с пюре",
        "fooddb editorial: grilled pork sausages over potato mashed with butter and milk, under "
        "fried onion",
        (I("fdc:172939", 150), I("bls:K110132", 220), I("bls:M111300", 50), I("bls:Q6A4000", 15),
         I("bls:G480100", 40), I("bls:Q320000", 10), I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(180, 280), serving_g=350),
 Recipe("beans-toast", "Beans on toast", "Фасоль в томате на тосте",
        "fooddb editorial: baked beans in tomato sauce over buttered toast",
        (I("ciqual:20194", 150), I("bls:B314072", 40), I("bls:Q6A4000", 8)),
        cooked_yield=1.0, kcal_band=(110, 170), serving_g=200),
 Recipe("bacon-sandwich", "Bacon sandwich", "Бутерброд с беконом",
        "fooddb editorial: white bread, butter and grilled bacon",
        (I("bls:B311000", 70), I("bls:Q6A4000", 10), I("bls:W415072", 45)),
        cooked_yield=1.0, kcal_band=(300, 420), serving_g=125),
 Recipe("jacket-potato-beans", "Jacket potato with baked beans", "Запечённая картошка с фасолью",
        "fooddb editorial: baked potato with baked beans, butter and cheddar",
        (I("bls:K110162", 220), I("ciqual:20194", 100), I("bls:Q6A4000", 10), I("bls:M303600", 30)),
        cooked_yield=1.0, kcal_band=(120, 180), serving_g=360),
 Recipe("buttered-toast", "Buttered toast", "Тост с маслом",
        "fooddb editorial: wheat toast with butter — toast the record already states, butter on top",
        (I("bls:B314072", 30), I("bls:Q6A4000", 7)),
        cooked_yield=1.0, kcal_band=(380, 460), serving_g=37),
 Recipe("texas-toast", "Texas toast (garlic butter toast)", "Техасский тост с чесноком",
        "fooddb editorial: thick white bread toasted with garlic butter",
        (I("bls:B311000", 60), I("bls:Q6A4000", 15), I("bls:G490100", 3)),
        cooked_yield=0.9, kcal_band=(380, 470), serving_g=60),
 Recipe("ploughmans", "Ploughman's lunch", "Плантаторский ланч",
        "fooddb editorial: the cold plate — bread, cheddar, butter, pickled gherkin, apple and ham",
        (I("bls:B311000", 60), I("bls:M303600", 60), I("bls:Q6A4000", 10), I("bls:G890902", 30),
         I("bls:F110100", 60), I("bls:W424000", 50)),
        cooked_yield=1.0, kcal_band=(200, 330), serving_g=270),
 Recipe("sticky-toffee", "Sticky toffee pudding", "Пудинг с финиками и ириской",
        "fooddb editorial: date sponge (dates, butter, sugar, egg, flour) under a butter-cream-"
        "sugar toffee sauce; the soaked pudding, both parts weighed",
        (I("bls:F504400", 100), I("bls:C214200", 100), I("bls:Q6A4000", 100), I("bls:S111000", 120),
         I("bls:E111100", 50), I("bls:M173800", 100)),
        cooked_yield=0.95, kcal_band=(330, 440), serving_g=120),
 Recipe("teacake", "Teacake", "Сдобная булочка с изюмом",
        "fooddb editorial: yeasted sweet bun with raisins — flour, milk, butter, sugar",
        (I("bls:C214200", 250), I("bls:M111300", 140), I("bls:Q6A4000", 30), I("bls:S111000", 25),
         I("bls:F840100", 60), I("bls:R459000", 5), I("ciqual:11017", 4)),
        cooked_yield=0.88, kcal_band=(290, 360), serving_g=80),
 Recipe("roasted-vegetables", "Roasted vegetables", "Запечённые овощи",
        "fooddb editorial: mixed vegetables — carrot, pepper, zucchini, onion — oiled and roasted; "
        "~25 % of the weight leaves the tray",
        (I("bls:G620100", 100), I("bls:G543100", 100), I("ciqual:20020", 100), I("bls:G480100", 60),
         I("ciqual:20053", 100), I("bls:Q120000", 25), I("ciqual:11017", 4)),
        cooked_yield=0.75, kcal_band=(70, 120), serving_g=200),
 Recipe("roasted-beetroot", "Roasted beetroot", "Запечённая свёкла",
        "fooddb editorial: beetroot oiled and roasted; ~25 % of the weight leaves",
        (I("bls:G613100", 300), I("bls:Q120000", 15), I("ciqual:11017", 3)),
        cooked_yield=0.75, kcal_band=(70, 120), serving_g=150),
 Recipe("chicken-tikka", "Chicken tikka", "Курица тикка",
        "fooddb editorial: chicken marinated in yogurt with cumin, coriander and chili, grilled — "
        "the skewer loses ~30 %",
        (I("bls:V413000", 300), I("ciqual:19593", 80), I("fdc:170923", 4), I("fdc:170921", 4),
         I("fdc:170932", 3), I("bls:F601600", 10), I("ciqual:11017", 5)),
        cooked_yield=0.7, kcal_band=(140, 220), serving_g=150),
 Recipe("jalfrezi", "Chicken jalfrezi", "Курица джалфрези",
        "fooddb editorial: chicken stir-fried with pepper, onion and tomato, chili-hot; ~10 % lost",
        (I("bls:V413000", 250), I("bls:G543100", 150), I("bls:G480100", 100), I("bls:G561100", 150),
         I("fdc:170106", 10), I("bls:Q320000", 20), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(90, 140), serving_g=300),
 Recipe("vinaigrette-balsamic", "Balsamic vinaigrette", "Бальзамическая заправка",
        "fooddb editorial: olive oil beaten with balsamic vinegar, mustard and salt, ~3:1",
        (I("bls:Q120000", 75), I("matvaretabellen:10.129", 25), I("bls:R132000", 5), I("ciqual:11017", 2)),
        cooked_yield=1.0, kcal_band=(560, 680), serving_g=15),
 Recipe("shakshuka", "Shakshuka", "Шакшука",
        "fooddb editorial: eggs poached in a tomato, pepper and onion stew; ~10 % evaporates",
        (I("bls:G561100", 300), I("bls:G543100", 120), I("bls:G480100", 80), I("bls:E111100", 150),
         I("bls:Q120000", 30), I("bls:G490100", 8), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(90, 140), serving_g=300),
 Recipe("souvlaki", "Souvlaki, pork", "Сувлаки из свинины",
        "fooddb editorial: pork skewers marinated with lemon, oil and oregano, grilled — loses "
        "~35 % to juice and fat",
        (I("bls:U632100", 400), I("bls:F601600", 15), I("bls:Q120000", 20), I("fdc:171328", 3),
         I("ciqual:11017", 6)),
        cooked_yield=0.65, kcal_band=(190, 320), serving_g=180),
 Recipe("fattoush", "Fattoush", "Фаттуш",
        "fooddb editorial: Levantine bread salad — tomato, cucumber, lettuce and onion with fried "
        "pita pieces under oil and lemon; mixed cold",
        (I("ciqual:7180", 50), I("bls:G561100", 150), I("bls:G520100", 120), I("bls:G107100", 60),
         I("bls:G480100", 30), I("bls:Q120000", 30), I("bls:F601600", 15), I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(90, 150), serving_g=200),
 Recipe("shawarma-chicken", "Chicken shawarma wrap", "Шаурма с курицей",
        "fooddb editorial: grilled spiced chicken in flatbread with garlic sauce, pickles and "
        "tomato — the filled wrap, both parts weighed",
        (I("bls:V4A5172", 180), I("bls:B782100", 120), I("bls:G520100", 60), I("bls:G561100", 60),
         I("bls:G520802", 30), I("ciqual:11054", 40), I("bls:G490100", 5), I("bls:Q320000", 15)),
        cooked_yield=1.0, kcal_band=(180, 260), serving_g=300),
 Recipe("shawarma-beef", "Beef shawarma wrap", "Шаурма с говядиной",
        "fooddb editorial: grilled spiced beef in flatbread with garlic sauce, pickles and onion",
        (I("bls:U163182", 180), I("bls:B782100", 120), I("bls:G561100", 60), I("bls:G520802", 30),
         I("bls:G480100", 40), I("ciqual:11054", 40), I("bls:G490100", 5), I("bls:Q320000", 15)),
        cooked_yield=1.0, kcal_band=(190, 280), serving_g=300),
 Recipe("kabsa", "Chicken kabsa", "Кабса с курицей",
        "fooddb editorial: Saudi spiced rice — chicken simmered with tomato, then rice cooked in "
        "the broth; ~5 % evaporates",
        (I("bls:V414100", 200), I("bls:C352000", 150), I("bls:G561100", 100), I("bls:R160000", 20),
         I("bls:G480100", 60), I("fdc:170931", 3), I("ciqual:11052", 2), I("ciqual:11075", 2),
         I("ciqual:18066", 350), I("bls:Q320000", 15), I("ciqual:11017", 6)),
        cooked_yield=0.95, kcal_band=(110, 180), serving_g=350),
 Recipe("ful-medames", "Ful medames", "Фул медамес",
        "fooddb editorial: stewed fava beans with olive oil, lemon and garlic",
        (I("fdc:173753", 300), I("bls:Q120000", 20), I("bls:F601600", 15), I("bls:G490100", 5),
         I("fdc:170923", 2), I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(105, 165), serving_g=200),
 Recipe("adana-kebab", "Adana kebab", "Адана-кебаб",
        "fooddb editorial: hand-minced lamb with tail fat and chili, grilled on skewers — fat drips "
        "to ~70 %",
        (I("bls:U807000", 300), I("bls:Q880000", 60), I("fdc:170932", 5), I("bls:G543100", 30),
         I("ciqual:11017", 6)),
        cooked_yield=0.7, kcal_band=(220, 340), serving_g=200),
 Recipe("muhammara", "Muhammara", "Мухаммара",
        "fooddb editorial: Syrian dip — roasted peppers ground with walnuts, bread crumbs, oil and "
        "lemon",
        (I("bls:G543100", 300), I("bls:H120100", 100), I("bls:B821000", 50), I("bls:Q120000", 40),
         I("bls:F601600", 15), I("fdc:170106", 5), I("ciqual:11017", 6)),
        cooked_yield=0.85, kcal_band=(220, 320), serving_g=50),
 Recipe("manakish", "Manakish (za'atar flatbread)", "Манакиш",
        "fooddb editorial: flatbread under a thyme-sesame-olive-oil paste; baking loses ~12 %",
        (I("bls:C214200", 250), I("ciqual:18066", 130), I("bls:R459000", 4), I("bls:Q120000", 45),
         I("fdc:170151", 20), I("ciqual:11038", 15), I("ciqual:11035", 10), I("ciqual:11017", 5)),
        cooked_yield=0.88, kcal_band=(260, 350), serving_g=150),
 Recipe("stuffed-zucchini", "Stuffed zucchini", "Фаршированные кабачки",
        "fooddb editorial: zucchini boats of mince, rice and tomato, baked; ~10 % lost",
        (I("ciqual:20020", 300), I("bls:U050100", 200), I("bls:C352032", 80), I("bls:G561100", 80),
         I("bls:G480100", 50), I("bls:Q320000", 15), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(80, 140), serving_g=300),
 Recipe("risotto-mushroom", "Mushroom risotto", "Грибной ризотто",
        "fooddb editorial: rice simmered in stock with mushrooms, finished with butter and parmesan",
        (I("bls:C352000", 150), I("bls:K701152", 150), I("ciqual:18066", 450), I("bls:Q6A4000", 40),
         I("bls:M306400", 30), I("bls:G480100", 40), I("bls:P210000", 50), I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(120, 180), serving_g=300),
 Recipe("fettuccine-alfredo", "Fettuccine Alfredo", "Феттуччине альфредо",
        "fooddb editorial: egg pasta tossed in butter, cream and parmesan — the boiled pasta takes "
        "up water",
        (I("bls:E432000", 150), I("bls:Q6A4000", 50), I("bls:M173800", 100), I("bls:M306400", 40),
         I("ciqual:18066", 150), I("ciqual:11017", 3)),
        cooked_yield=1.0, kcal_band=(240, 340), serving_g=250),
 Recipe("onigiri", "Onigiri, salmon filling", "Онигири с лососем",
        "fooddb editorial: rice balls around grilled salmon, wrapped in nori; nothing is lost",
        (I("bls:C352032", 250), I("bls:T410072", 60), I("bls:G995000", 6), I("ciqual:11017", 3)),
        cooked_yield=1.0, kcal_band=(115, 175), serving_g=120),
 Recipe("okonomiyaki", "Okonomiyaki", "Окономияки",
        "fooddb editorial: Osaka cabbage pancake — batter with cabbage and pork belly, pan-fried; "
        "~10 % lost",
        (I("bls:C214200", 80), I("ciqual:18066", 80), I("bls:E111100", 60), I("bls:G342100", 250),
         I("bls:U583100", 120), I("bls:Q320000", 15), I("ciqual:11017", 3)),
        cooked_yield=0.9, kcal_band=(140, 220), serving_g=250),
 Recipe("dan-dan", "Dan dan noodles", "Даньдань мянь",
        "fooddb editorial: noodles under pork mince fried with chili, soy and sesame — the boiled "
        "noodles take up water",
        (I("bls:E401000", 150), I("bls:U020100", 120), I("bls:Q230000", 10), I("fdc:170106", 10),
         I("bls:R143000", 15), I("bls:G490100", 5), I("fdc:170151", 8), I("ciqual:18066", 200)),
        cooked_yield=1.0, kcal_band=(150, 230), serving_g=300),
 Recipe("mapo-tofu", "Mapo tofu", "Мапо тофу",
        "fooddb editorial: tofu simmered with pork mince in a chili-bean sauce — chili bean paste "
        "is not in the tables, miso plus chili and soy stands in",
        (I("bls:H861000", 300), I("bls:U020100", 100), I("bls:H862200", 30), I("fdc:170106", 8),
         I("bls:R143000", 10), I("bls:G490100", 5), I("bls:Q230000", 10), I("ciqual:18066", 100),
         I("fdc:170923", 3)),
        cooked_yield=1.0, kcal_band=(80, 140), serving_g=250),
 Recipe("char-siu", "Char siu (Chinese BBQ pork)", "Часю",
        "fooddb editorial: pork shoulder glazed with honey, soy and hoisin, roasted — loses ~25 %",
        (I("bls:U571100", 400), I("bls:S121000", 40), I("bls:R143000", 30), I("fdc:172886", 40),
         I("ciqual:11017", 5)),
        cooked_yield=0.75, kcal_band=(220, 330), serving_g=150),
 Recipe("bulgogi", "Bulgogi", "Пульгоги",
        "fooddb editorial: thin beef marinated in soy, sugar, sesame and garlic, grilled — loses "
        "~25 %",
        (I("bls:U184100", 300), I("bls:R143000", 40), I("bls:S111000", 20), I("bls:Q230000", 15),
         I("bls:G490100", 8), I("bls:G480100", 40), I("fdc:170151", 5)),
        cooked_yield=0.75, kcal_band=(160, 250), serving_g=200),
 Recipe("korean-fried-chicken", "Korean fried chicken", "Корейская жареная курица",
        "fooddb editorial: twice-fried battered chicken glazed in gochujang sauce — the paste is "
        "not in the tables, miso with chili and sugar stands in; ~10 % lost, oil in",
        (I("bls:V4A5100", 300), I("fdc:169698", 40), I("bls:Q320000", 50), I("bls:H862200", 30),
         I("fdc:170932", 8), I("bls:S111000", 25), I("bls:R121000", 10), I("bls:G490100", 6)),
        cooked_yield=0.9, kcal_band=(230, 340), serving_g=200),
 Recipe("japchae", "Japchae", "Чапчхе",
        "fooddb editorial: glass noodles stir-fried with beef, spinach, carrot and mushroom in soy "
        "and sesame; the boiled noodles take up water",
        (I("bls:H030400", 80), I("bls:U184100", 100), I("bls:G211152", 80), I("bls:G620100", 60),
         I("bls:K701152", 40), I("bls:G480100", 40), I("bls:R143000", 20), I("bls:Q230000", 15),
         I("bls:S111000", 10), I("ciqual:18066", 150)),
        cooked_yield=1.0, kcal_band=(110, 170), serving_g=250),
 Recipe("kimchi-jjigae", "Kimchi jjigae (kimchi stew)", "Кимчи-ччиге",
        "fooddb editorial: kimchi stewed with pork and tofu; ~5 % evaporates",
        (I("fdc:2710077", 250), I("bls:U632100", 120), I("bls:H861000", 150), I("ciqual:18066", 300),
         I("bls:G480100", 40), I("bls:Q230000", 8)),
        cooked_yield=0.95, kcal_band=(50, 90), serving_g=300),
 Recipe("banh-mi", "Banh mi", "Бан ми",
        "fooddb editorial: baguette with pork, pâté, pickled carrot, cucumber, cilantro and "
        "mayonnaise — the filled loaf",
        (I("bls:B781200", 80), I("bls:U632100", 60), I("bls:W395000", 30), I("bls:G620100", 30),
         I("bls:G520100", 30), I("fdc:169997", 5), I("ciqual:11054", 20), I("bls:R121000", 5)),
        cooked_yield=1.0, kcal_band=(200, 290), serving_g=200),
 Recipe("massaman", "Massaman curry", "Массаман-карри",
        "fooddb editorial: beef simmered in coconut milk with potato, peanuts, onion and spices; "
        "~10 % evaporates",
        (I("bls:U184100", 200), I("bls:H154000", 250), I("bls:K110100", 120), I("bls:H110600", 30),
         I("bls:G480100", 50), I("ciqual:11005", 8), I("ciqual:11052", 2), I("ciqual:11075", 2),
         I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(130, 200), serving_g=300),
 Recipe("tom-kha-gai", "Tom kha gai", "Том кха кай",
        "fooddb editorial: chicken in coconut milk with mushroom, lime and chili — galangal is not "
        "in the tables, ginger stands in; ~5 % evaporates",
        (I("bls:V413000", 150), I("bls:H154000", 300), I("bls:K701100", 80), I("bls:F602600", 15),
         I("fdc:170106", 5), I("bls:R211200", 10), I("ciqual:11017", 5), I("ciqual:18066", 100)),
        cooked_yield=0.95, kcal_band=(90, 150), serving_g=300),
 Recipe("tom-yum", "Tom yum", "Том ям",
        "fooddb editorial: hot-sour shrimp soup — shrimp and mushroom with lime, chili, ginger and "
        "lemongrass aromatics (lemongrass and fish sauce are not in the tables; ginger and soy "
        "stand in); ~5 % evaporates",
        (I("bls:T753100", 120), I("bls:K701100", 80), I("ciqual:18066", 500), I("bls:F602600", 20),
         I("fdc:170106", 8), I("bls:R211200", 10), I("bls:R143000", 10), I("bls:G561100", 50),
         I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(20, 45), serving_g=300),
 Recipe("som-tam", "Green papaya salad (som tam)", "Сом там",
        "fooddb editorial: pounded unripe papaya with lime, chili, peanuts and tomato — fish sauce "
        "is not in the tables, soy stands in; mixed cold",
        (I("bls:F517100", 250), I("bls:F602600", 20), I("fdc:170106", 8), I("bls:H110600", 30),
         I("bls:G561100", 60), I("bls:R143000", 15), I("bls:S111000", 8)),
        cooked_yield=1.0, kcal_band=(55, 100), serving_g=150),
 Recipe("rendang", "Beef rendang", "Говядина ренданг",
        "fooddb editorial: beef braised in coconut milk with ginger, garlic and chili until nearly "
        "dry — ~40 % evaporates",
        (I("bls:U184100", 400), I("bls:H154000", 300), I("bls:R211200", 15), I("bls:G490100", 10),
         I("fdc:170106", 10), I("bls:G480100", 60), I("ciqual:11017", 5)),
        cooked_yield=0.6, kcal_band=(160, 260), serving_g=200),
 Recipe("hainanese-chicken-rice", "Hainanese chicken rice", "Хайнаньский рис с курицей",
        "fooddb editorial: poached chicken over rice cooked in the broth with ginger and garlic — "
        "the plate",
        (I("bls:V413132", 150), I("bls:C352000", 120), I("ciqual:18066", 250), I("bls:R211200", 8),
         I("bls:G490100", 5), I("bls:G520100", 40), I("bls:R143000", 10)),
        cooked_yield=0.95, kcal_band=(105, 175), serving_g=350),
 Recipe("adobo", "Chicken adobo", "Курица адобо",
        "fooddb editorial: chicken braised in vinegar, soy, garlic and bay; ~20 % evaporates",
        (I("bls:V414100", 300), I("bls:R121000", 40), I("bls:R143000", 30), I("bls:G490100", 10),
         I("ciqual:11053", 2), I("ciqual:18066", 100), I("ciqual:11017", 4)),
        cooked_yield=0.8, kcal_band=(120, 200), serving_g=250),
 Recipe("larb", "Larb (minced chicken salad)", "Ларб",
        "fooddb editorial: minced chicken with lime, chili, mint and toasted-rice powder — fish "
        "sauce is not in the tables, soy stands in",
        (I("bls:V413000", 250), I("bls:F602600", 30), I("fdc:170106", 8), I("ciqual:11027", 15),
         I("bls:G480100", 50), I("fdc:170151", 10), I("bls:R143000", 15), I("ciqual:11017", 3)),
        cooked_yield=0.85, kcal_band=(100, 160), serving_g=150),
 Recipe("teriyaki-salmon", "Teriyaki salmon", "Лосось терияки",
        "fooddb editorial: salmon grilled under a soy-sugar glaze — mirin is not in the tables, "
        "sugar stands in",
        (I("bls:T410072", 200), I("bls:R143000", 30), I("bls:S111000", 15), I("fdc:167723", 20)),
        cooked_yield=0.95, kcal_band=(200, 280), serving_g=150),
 Recipe("jollof", "Jollof rice", "Рис джоллоф",
        "fooddb editorial: rice simmered in a tomato-pepper-onion base with oil; ~5 % evaporates",
        (I("bls:C352000", 150), I("bls:G561100", 150), I("bls:R160000", 30), I("bls:G543100", 60),
         I("bls:G480100", 60), I("fdc:170106", 5), I("bls:Q320000", 25), I("ciqual:18066", 300),
         I("ciqual:11017", 5)),
        cooked_yield=0.95, kcal_band=(100, 160), serving_g=300),
 Recipe("suya", "Suya", "Суйя",
        "fooddb editorial: beef skewers coated in ground-peanut chili spice, grilled — loses ~30 %",
        (I("bls:U184100", 300), I("bls:H110600", 50), I("fdc:170932", 8), I("bls:G490100", 5),
         I("ciqual:11017", 5), I("bls:Q320000", 10)),
        cooked_yield=0.7, kcal_band=(200, 300), serving_g=150),
 Recipe("doro-wat", "Doro wat", "Доро ват",
        "fooddb editorial: Ethiopian chicken stew — onion cooked down with berbere (modelled as "
        "chili, paprika and ginger), butter and egg; ~15 % evaporates",
        (I("bls:V414100", 250), I("bls:G480100", 200), I("fdc:170932", 10), I("ciqual:11049", 10),
         I("bls:R211200", 5), I("bls:Q6A4000", 40), I("bls:E111132", 60), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(130, 210), serving_g=250),
 Recipe("bobotie", "Bobotie", "Боботи",
        "fooddb editorial: Cape mince bake — curried mince bound with milk-soaked bread and an egg "
        "top; ~10 % lost",
        (I("bls:U050100", 300), I("bls:B311000", 50), I("bls:M111300", 100), I("bls:E111100", 50),
         I("bls:G480100", 80), I("ciqual:11005", 8), I("bls:F840100", 30), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(140, 220), serving_g=200),
 Recipe("tagine-lamb", "Lamb tagine with apricots", "Бараний тажин с абрикосами",
        "fooddb editorial: lamb stewed with onion, chickpeas, dried apricots and spices; ~15 % "
        "evaporates",
        (I("bls:U807000", 250), I("bls:G480100", 80), I("bls:H720902", 100), I("bls:F201400", 60),
         I("bls:G561100", 100), I("fdc:170919", 3), I("fdc:170923", 3), I("bls:R211200", 5),
         I("ciqual:18066", 150), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(85, 150), serving_g=300),
 Recipe("koshari", "Koshari", "Кошари",
        "fooddb editorial: the Egyptian plate — rice, lentils and pasta under tomato sauce with "
        "chickpeas and fried onion",
        (I("bls:C352032", 150), I("bls:H730132", 80), I("bls:E401032", 60), I("bls:G561100", 120),
         I("bls:H720902", 60), I("bls:G480100", 60), I("bls:Q320000", 20), I("bls:G490100", 5),
         I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(110, 175), serving_g=350),
 Recipe("moi-moi", "Moi moi", "Мои-мои",
        "fooddb editorial: steamed black-eyed pea pudding with oil, pepper and onion — pureed "
        "beans steamed firm",
        (I("bls:H702132", 300), I("bls:Q320000", 30), I("fdc:170106", 10), I("bls:G480100", 60),
         I("bls:E111100", 40), I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(120, 180), serving_g=200),
 Recipe("puff-puff", "Puff-puff", "Паф-паф",
        "fooddb editorial: West African fried dough — yeasted sweet batter deep-fried; ~10 % out, "
        "oil in",
        (I("bls:C214200", 250), I("ciqual:18066", 220), I("bls:S111000", 60), I("bls:R459000", 5),
         I("bls:Q320000", 60)),
        cooked_yield=0.9, kcal_band=(280, 400), serving_g=80),
 Recipe("piri-piri-chicken", "Piri piri chicken", "Курица пири-пири",
        "fooddb editorial: chicken grilled in a chili-lemon-garlic-oil marinade — loses ~30 %; "
        "the marinade holds ~30 g oil but most of it drips off the grill, ~10 g stays on the bird",
        (I("bls:V414100", 350), I("fdc:170106", 15), I("bls:F601600", 20), I("bls:G490100", 8),
         I("bls:Q120000", 10), I("ciqual:11049", 5), I("ciqual:11017", 6)),
        cooked_yield=0.7, kcal_band=(180, 320), serving_g=250),
 Recipe("groundnut-stew", "Groundnut stew (maafe)", "Арахисовое рагу",
        "fooddb editorial: chicken stewed in a peanut-tomato base with onion; ~15 % evaporates",
        (I("bls:V414100", 250), I("bls:H110800", 80), I("bls:G561100", 150), I("bls:R160000", 20),
         I("bls:G480100", 80), I("fdc:170106", 5), I("ciqual:18066", 150), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(140, 220), serving_g=300),
 Recipe("mandazi", "Mandazi", "Мандази",
        "fooddb editorial: East African fried dough — coconut-milk dough with sugar and cardamom, "
        "deep-fried; ~10 % out, oil in",
        (I("bls:C214200", 250), I("bls:H154000", 150), I("bls:S111000", 40), I("bls:R459000", 4),
         I("ciqual:11075", 2), I("bls:Q320000", 50)),
        cooked_yield=0.85, kcal_band=(330, 450), serving_g=80),
 Recipe("yassa", "Chicken yassa", "Курица ясса",
        "fooddb editorial: chicken marinated in lemon and mustard, stewed with a lot of onion; "
        "~15 % evaporates",
        (I("bls:V414100", 250), I("bls:G480100", 250), I("bls:F601600", 40), I("bls:R132000", 20),
         I("bls:Q120000", 30), I("ciqual:18066", 100), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(100, 160), serving_g=300),
 Recipe("kheer", "Kheer", "Кхир",
        "fooddb editorial: rice simmered in milk until thick, with sugar and cardamom — the milk "
        "reduces ~25 %",
        (I("bls:C352000", 60), I("bls:M111300", 500), I("bls:S111000", 60), I("ciqual:11075", 2)),
        cooked_yield=0.75, kcal_band=(120, 170), serving_g=150),
 Recipe("jalebi", "Jalebi", "Джалеби",
        "fooddb editorial: fermented flour-yogurt batter fried in spirals, soaked in sugar syrup — "
        "water out, syrup and oil in",
        (I("bls:C214200", 100), I("ciqual:19593", 80), I("bls:S111000", 150), I("ciqual:18066", 100),
         I("bls:Q320000", 40)),
        cooked_yield=0.9, kcal_band=(300, 420), serving_g=80),
 Recipe("mango-sticky-rice", "Mango sticky rice", "Клейкий рис с манго",
        "fooddb editorial: steamed glutinous rice under sweetened coconut milk with fresh mango",
        (I("fdc:169711", 200), I("bls:H154000", 120), I("bls:S111000", 25), I("bls:F516100", 120),
         I("ciqual:11017", 1)),
        cooked_yield=1.0, kcal_band=(120, 190), serving_g=200),
 Recipe("masala-chai", "Masala chai", "Масала-чай",
        "fooddb editorial: black tea simmered with milk, sugar, ginger and spices",
        (I("bls:N630000", 400), I("bls:M111300", 200), I("bls:S111000", 30), I("bls:R211200", 5),
         I("ciqual:11075", 2), I("ciqual:11052", 1)),
        cooked_yield=0.95, kcal_band=(35, 60), serving_g=250),
 Recipe("mango-lassi", "Mango lassi", "Манго-ласси",
        "fooddb editorial: mango blended with yogurt, milk and a little sugar",
        (I("bls:F516100", 200), I("ciqual:19593", 300), I("bls:M111300", 100), I("bls:S111000", 20)),
        cooked_yield=1.0, kcal_band=(60, 100), serving_g=250),
 Recipe("dal-makhani", "Dal makhani", "Дал макхани",
        "fooddb editorial: black urad and kidney beans simmered with butter, cream and tomato — "
        "no urad record states carbohydrate, boiled mung stands in for the urad",
        (I("bls:H770132", 150), I("bls:H742132", 80), I("bls:Q6A4000", 30), I("bls:M173800", 40),
         I("bls:G561100", 80), I("bls:R211200", 5), I("bls:G490100", 5), I("ciqual:18066", 200),
         I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(90, 160), serving_g=250),
 Recipe("paneer-tikka", "Paneer tikka", "Панир тикка",
        "fooddb editorial: paneer cubes marinated in spiced yogurt, grilled — loses ~15 %",
        (I("matvaretabellen:01.301", 300), I("ciqual:19593", 80), I("fdc:170923", 4), I("ciqual:11088", 3),
         I("bls:G543100", 50), I("bls:Q320000", 10)),
        cooked_yield=0.85, kcal_band=(230, 320), serving_g=150),
 Recipe("aloo-paratha", "Aloo paratha", "Алу паратха",
        "fooddb editorial: wholewheat flatbread around spiced mashed potato, fried on the griddle "
        "with oil",
        (I("bls:C211000", 150), I("ciqual:18066", 90), I("bls:K110132", 150), I("bls:G480100", 30),
         I("fdc:170923", 3), I("bls:Q320000", 20), I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(180, 260), serving_g=150),
 Recipe("vindaloo", "Pork vindaloo", "Свиной виндалу",
        "fooddb editorial: pork marinated in vinegar, garlic and chili, braised hot; ~15 % "
        "evaporates",
        (I("bls:U632100", 300), I("bls:R121000", 40), I("bls:G490100", 12), I("fdc:170932", 8),
         I("fdc:170923", 4), I("bls:G480100", 80), I("bls:Q320000", 15), I("ciqual:18066", 100)),
        cooked_yield=0.85, kcal_band=(130, 230), serving_g=250),
 Recipe("poha", "Poha", "Поха",
        "fooddb editorial: flattened rice steamed with onion, potato, peanuts and turmeric — rice "
        "flakes are not in the tables, plain rice stands in",
        (I("bls:C352000", 120), I("ciqual:18066", 200), I("bls:G480100", 60), I("bls:K110100", 80),
         I("bls:H110600", 30), I("ciqual:11089", 2), I("bls:G760132", 40), I("bls:Q320000", 15),
         I("ciqual:11017", 4), I("bls:F601600", 10)),
        cooked_yield=0.97, kcal_band=(110, 170), serving_g=200),
 Recipe("nihari", "Nihari", "Нихари",
        "fooddb editorial: slow-braised beef shank thickened with wheat flour, ginger and spices; "
        "~20 % evaporates",
        (I("bls:U151100", 300), I("bls:C214200", 30), I("bls:R211200", 8), I("bls:G490100", 8),
         I("bls:G480100", 80), I("fdc:170923", 4), I("fdc:170932", 4), I("bls:Q320000", 30),
         I("ciqual:18066", 300)),
        cooked_yield=0.8, kcal_band=(130, 210), serving_g=300),
 Recipe("haleem", "Haleem", "Халим",
        "fooddb editorial: wheat, lentils and chicken pounded into a porridge with ghee and spices; "
        "~10 % evaporates",
        (I("bls:C117000", 100), I("bls:H730132", 80), I("bls:V413000", 150), I("cofid:12-502", 40),
         I("bls:G480100", 60), I("bls:R211200", 5), I("fdc:170923", 4), I("ciqual:18066", 400)),
        cooked_yield=0.9, kcal_band=(110, 180), serving_g=300),
 Recipe("chole-bhature", "Chole bhature", "Чоле-бхатуре",
        "fooddb editorial: spiced chickpea curry with a fried yogurt-leavened bread — the plate, "
        "both weighed",
        (I("bls:H720902", 200), I("bls:G561100", 80), I("bls:G480100", 50), I("fdc:170923", 4),
         I("fdc:170932", 4), I("bls:R211200", 5), I("bls:C214200", 120), I("ciqual:19593", 40),
         I("bls:Q320000", 45), I("ciqual:11017", 5)),
        cooked_yield=0.95, kcal_band=(180, 260), serving_g=300),
 Recipe("chili-oil", "Chili oil", "Чили-масло",
        "fooddb editorial: dried chili steeped in hot sunflower oil and left in it",
        (I("bls:Q320000", 250), I("ciqual:11088", 30)),
        cooked_yield=1.0, kcal_band=(750, 900), serving_g=10),
 Recipe("chimichurri", "Chimichurri", "Чимичурри",
        "fooddb editorial: parsley, garlic, oregano and chili in oil and vinegar; mixed cold",
        (I("bls:G250100", 60), I("bls:G490100", 20), I("ciqual:11035", 5), I("ciqual:11088", 3),
         I("bls:Q120000", 120), I("ciqual:11220", 40), I("ciqual:11017", 5)),
        cooked_yield=1.0, kcal_band=(400, 550), serving_g=30),
 Recipe("feijoada", "Feijoada", "Фейжоада",
        "fooddb editorial: black beans stewed with pork and smoked sausage; ~10 % evaporates — "
        "kabanossi stands in for the smoked sausage, whose record states no carbohydrate",
        (I("fdc:173735", 300), I("bls:U632100", 120), I("bls:W193000", 80), I("bls:G480100", 60),
         I("bls:G490100", 8), I("ciqual:11053", 2), I("ciqual:18066", 200), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(120, 190), serving_g=300),
 Recipe("lomo-saltado", "Lomo saltado", "Ломо сальтадо",
        "fooddb editorial: beef stir-fried with onion, tomato and soy, over fries",
        (I("bls:U163182", 200), I("bls:G480100", 80), I("bls:G561100", 100), I("bls:R143000", 20),
         I("bls:K130592", 150), I("bls:Q320000", 15), I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(130, 230), serving_g=300),
 Recipe("pork-roast-dumplings", "Pork roast with dumplings", "Жаркое из свинины с кнедликами",
        "fooddb editorial: roasted pork shoulder with steamed bread dumplings and pan gravy",
        (I("bls:U571162", 150), I("bls:E606022", 150), I("bls:G480100", 40), I("ciqual:18066", 60),
         I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(140, 250), serving_g=330),
 Recipe("caesar-wrap", "Chicken Caesar wrap", "Ролл «Цезарь» с курицей",
        "fooddb editorial: grilled chicken, romaine, parmesan and dressing in a flour tortilla",
        (I("bls:B783012", 70), I("bls:V416172", 90), I("bls:G107100", 40), I("bls:M306400", 15),
         I("ciqual:11054", 25), I("bls:F601600", 3)),
        cooked_yield=1.0, kcal_band=(220, 300), serving_g=200),
 Recipe("mezze", "Mezze platter", "Меззе",
        "fooddb editorial: the small-plate spread — hummus, pita, olives and feta",
        (I("bls:H960000", 100), I("ciqual:7180", 80), I("bls:H510802", 30), I("bls:M012200", 40),
         I("bls:Q120000", 10)),
        cooked_yield=1.0, kcal_band=(220, 320), serving_g=200),
 Recipe("halva", "Halva, sesame", "Халва",
        "fooddb editorial: sesame halva — tahini beaten with hot sugar syrup; the syrup dries in",
        (I("bls:Q901000", 400), I("bls:S111000", 250), I("ciqual:18066", 60)),
        cooked_yield=0.95, kcal_band=(450, 570), serving_g=40),
 Recipe("lavash", "Lavash", "Лаваш",
        "fooddb editorial: thin flatbread — flour, water, salt, a little yeast; baking loses ~15 %",
        (I("bls:C214200", 300), I("ciqual:18066", 180), I("bls:R459000", 4), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(250, 300), serving_g=100),
 Recipe("labneh", "Labneh", "Лабне",
        "fooddb editorial: yogurt strained to a soft cheese — about half the weight leaves as whey",
        (I("ciqual:19593", 1000), I("ciqual:11017", 8)),
        cooked_yield=0.5, kcal_band=(90, 140), serving_g=100),
 # ── Spanish set ──
 Recipe("patatas-bravas", "Patatas bravas", "Пататас бравас",
        "fooddb editorial: fried potato cubes under the brava sauce — tomato with chili, paprika and "
        "vinegar",
        (I("bls:K110100", 300), I("bls:Q120000", 50), I("bls:G561100", 100), I("bls:R160000", 15),
         I("fdc:170932", 4), I("ciqual:11049", 4), I("bls:R121000", 8), I("bls:G490100", 5),
         I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(150, 230), serving_g=200),
 Recipe("salsa-brava", "Salsa brava", "Сальса брава",
        "fooddb editorial: the brava sauce itself — tomato cooked down with chili, paprika, garlic "
        "and vinegar",
        (I("bls:G561100", 300), I("bls:R160000", 40), I("fdc:170932", 5), I("ciqual:11049", 6),
         I("bls:G490100", 8), I("bls:R121000", 15), I("bls:Q120000", 20), I("ciqual:11017", 4)),
        cooked_yield=0.85, kcal_band=(60, 110), serving_g=50),
 Recipe("croquetas-jamon", "Croquetas de jamón", "Крокеты с хамоном",
        "fooddb editorial: thick béchamel with chopped cured ham, breaded and deep-fried; ~10 % "
        "lost, oil in",
        (I("bls:M111300", 300), I("bls:C214200", 60), I("bls:Q6A4000", 50), I("ciqual:28845", 100),
         I("bls:E111100", 30), I("bls:B821000", 80), I("bls:Q320000", 50), I("ciqual:11017", 4)),
        cooked_yield=0.9, kcal_band=(240, 340), serving_g=120),
 Recipe("croquetas-pollo", "Croquetas de pollo", "Крокеты с курицей",
        "fooddb editorial: thick béchamel with cooked chicken, breaded and deep-fried",
        (I("bls:M111300", 300), I("bls:C214200", 60), I("bls:Q6A4000", 50), I("bls:V413132", 100),
         I("bls:E111100", 30), I("bls:B821000", 80), I("bls:Q320000", 50), I("ciqual:11017", 4)),
        cooked_yield=0.9, kcal_band=(220, 320), serving_g=120),
 Recipe("churros", "Churros", "Чуррос",
        "fooddb editorial: flour-and-water dough piped into hot oil, sugared — the same batter as "
        "porras, which differ only in shape; frying drives the dough to ~63 % of the raw mix and "
        "the crust takes up ~90 g of frying oil",
        (I("bls:C214200", 250), I("ciqual:18066", 300), I("ciqual:11017", 4), I("bls:Q320000", 90),
         I("bls:S111000", 30)),
        cooked_yield=0.63, kcal_band=(280, 440), serving_g=100),
 Recipe("salmorejo", "Salmorejo", "Сальморехо",
        "fooddb editorial: cold tomato soup — tomato blended with bread, olive oil, garlic and "
        "vinegar until creamy",
        (I("bls:G561100", 500), I("bls:B311000", 100), I("bls:Q120000", 80), I("bls:G490100", 5),
         I("bls:R121000", 10), I("ciqual:11017", 5)),
        cooked_yield=1.0, kcal_band=(110, 180), serving_g=250),
 Recipe("sopa-de-ajo", "Sopa de ajo (Castilian garlic soup)", "Чесночный суп",
        "fooddb editorial: garlic and stale bread simmered with paprika, egg stirred in; sopa "
        "castellana is the same soup — ~10 % evaporates",
        (I("bls:G490100", 40), I("bls:B311000", 100), I("ciqual:11049", 8), I("bls:E111100", 60),
         I("ciqual:18066", 500), I("bls:Q120000", 30), I("ciqual:11017", 6)),
        cooked_yield=0.9, kcal_band=(60, 110), serving_g=300),
 Recipe("crema-calabacin", "Crema de calabacín", "Крем-суп из кабачков",
        "fooddb editorial: zucchini simmered with potato and onion, blended with cream",
        (I("ciqual:20020", 400), I("bls:K110100", 120), I("bls:G480100", 80), I("bls:M173800", 60),
         I("ciqual:18066", 300), I("ciqual:11017", 5)),
        cooked_yield=0.98, kcal_band=(35, 70), serving_g=250),
 Recipe("bocadillo-jamon", "Bocadillo de jamón", "Бокадильо с хамоном",
        "fooddb editorial: baguette with cured ham, rubbed tomato and olive oil",
        (I("bls:B781200", 80), I("ciqual:28845", 50), I("bls:G561100", 30), I("bls:Q120000", 8)),
        cooked_yield=1.0, kcal_band=(220, 300), serving_g=150),
 Recipe("bocadillo-tortilla", "Bocadillo de tortilla", "Бокадильо с тортильей",
        "fooddb editorial: baguette with a potato-and-onion omelette wedge",
        (I("bls:B781200", 80), I("bls:K110100", 80), I("bls:E111100", 60), I("bls:G480100", 20),
         I("bls:Q120000", 20), I("ciqual:11017", 3)),
        cooked_yield=0.95, kcal_band=(190, 270), serving_g=180),
 Recipe("tostada-aguacate", "Tostada con aguacate", "Тост с авокадо",
        "fooddb editorial: toast with avocado and olive oil",
        (I("bls:B314072", 30), I("bls:F502100", 60), I("bls:Q120000", 5), I("ciqual:11017", 1)),
        cooked_yield=1.0, kcal_band=(170, 240), serving_g=90),
 Recipe("paella-valenciana", "Paella valenciana", "Паэлья валенсиана",
        "fooddb editorial: chicken and rabbit with green beans and tomato, rice cooked in the broth; "
        "~10 % evaporates",
        (I("bls:V414100", 200), I("bls:V132100", 150), I("bls:G710132", 80), I("bls:G561100", 100),
         I("bls:C352000", 180), I("ciqual:18066", 500), I("bls:Q120000", 30), I("ciqual:11039", 1),
         I("ciqual:11017", 6)),
        cooked_yield=0.9, kcal_band=(120, 180), serving_g=350),
 Recipe("paella-marisco", "Paella de marisco", "Паэлья с морепродуктами",
        "fooddb editorial: shellfish paella — rice with shrimp, mussel and squid, pepper and tomato",
        (I("bls:T753100", 120), I("bls:T792132", 120), I("ciqual:10001", 100), I("bls:G543100", 80),
         I("bls:G561100", 100), I("bls:C352000", 180), I("ciqual:18066", 500), I("bls:Q120000", 30),
         I("ciqual:11039", 1), I("ciqual:11017", 6)),
        cooked_yield=0.9, kcal_band=(90, 140), serving_g=350),
 Recipe("fideua", "Fideuá", "Фидеуа",
        "fooddb editorial: noodle paella — short pasta toasted and simmered with squid, shrimp and "
        "tomato",
        (I("bls:E401000", 150), I("ciqual:10001", 120), I("bls:T753100", 100), I("bls:G561100", 100),
         I("bls:G480100", 40), I("ciqual:18066", 400), I("bls:Q120000", 25), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(100, 150), serving_g=300),
 Recipe("arroz-cubana", "Arroz a la cubana", "Рис по-кубински",
        "fooddb editorial: white rice with a fried egg, tomato sauce and fried banana",
        (I("bls:C352032", 150), I("bls:E111182", 60), I("bls:G561100", 80), I("bls:F503100", 80),
         I("bls:Q120000", 20), I("ciqual:11017", 3)),
        cooked_yield=1.0, kcal_band=(115, 190), serving_g=300),
 Recipe("gambas-ajillo", "Gambas al ajillo", "Креветки аль ахильо",
        "fooddb editorial: shrimp sizzled in olive oil with garlic and chili",
        (I("bls:T753100", 200), I("bls:Q120000", 60), I("bls:G490100", 15), I("fdc:170106", 5),
         I("ciqual:11017", 3)),
        cooked_yield=0.9, kcal_band=(200, 320), serving_g=150),
 Recipe("pollo-ajillo", "Pollo al ajillo", "Курица аль ахильо",
        "fooddb editorial: chicken browned in olive oil with garlic and a splash of wine; ~15 % "
        "lost",
        (I("bls:V414100", 300), I("bls:Q120000", 40), I("bls:G490100", 15), I("ciqual:5215", 60),
         I("ciqual:11053", 2), I("ciqual:11017", 5)),
        cooked_yield=0.85, kcal_band=(180, 290), serving_g=200),
 Recipe("pimientos-padron", "Pimientos de Padrón", "Перцы падрон",
        "fooddb editorial: small green peppers fried in olive oil with salt — green pepper stands "
        "in for the Padrón variety; ~20 % lost",
        (I("bls:G541100", 250), I("bls:Q120000", 20), I("ciqual:11017", 3)),
        cooked_yield=0.8, kcal_band=(90, 150), serving_g=100),
 Recipe("escalivada", "Escalivada", "Эскаливада",
        "fooddb editorial: roasted eggplant, pepper and onion torn and dressed with oil; ~25 % "
        "lost",
        (I("ciqual:20053", 300), I("bls:G543100", 200), I("bls:G480100", 100), I("bls:Q120000", 30),
         I("ciqual:11017", 4)),
        cooked_yield=0.75, kcal_band=(60, 110), serving_g=150),
 Recipe("verduras-plancha", "Verduras a la plancha", "Овощи на гриле",
        "fooddb editorial: griddled vegetables — zucchini, eggplant, pepper and onion with oil; "
        "~25 % lost",
        (I("ciqual:20020", 150), I("ciqual:20053", 150), I("bls:G543100", 100), I("bls:G480100", 60),
         I("bls:Q120000", 20), I("ciqual:11017", 4)),
        cooked_yield=0.75, kcal_band=(70, 120), serving_g=200),
 Recipe("cocido", "Cocido madrileño", "Косидо",
        "fooddb editorial: the Madrid stew — chickpeas simmered with beef, pork belly, chorizo, "
        "cabbage and potato; ~10 % evaporates",
        (I("bls:H720902", 200), I("bls:U184100", 100), I("bls:U583132", 80), I("cofid:19-516", 60),
         I("bls:G342100", 120), I("bls:K110100", 120), I("bls:G620100", 50), I("ciqual:18066", 300),
         I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(100, 180), serving_g=350),
 Recipe("marmitako", "Marmitako", "Мармитако",
        "fooddb editorial: Basque tuna-potato stew with pepper and onion; ~10 % evaporates",
        (I("bls:T120100", 200),
         I("bls:K110100", 250), I("bls:G543100", 100), I("bls:G480100", 80), I("bls:G561100", 100),
         I("bls:Q120000", 20), I("ciqual:18066", 300), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(70, 120), serving_g=300),
 Recipe("fabes-almejas", "Fabes con almejas (beans with clams)", "Фабада с моллюсками",
        "fooddb editorial: Asturian white beans stewed with clams, garlic and a little wine; ~10 % "
        "evaporates",
        (I("fdc:173750", 250), I("bls:T791132", 100), I("bls:G490100", 8), I("bls:P210000", 60),
         I("bls:Q120000", 15), I("ciqual:18066", 250), I("bls:G250100", 5), I("ciqual:11017", 4)),
        cooked_yield=0.9, kcal_band=(90, 140), serving_g=300),
 Recipe("callos", "Callos a la madrileña", "Кальос",
        "fooddb editorial: Madrid tripe stew — boiled tripe with chorizo, chickpeas and ham in a "
        "paprika broth; ~10 % evaporates",
        (I("bls:V551132", 250), I("cofid:19-516", 60), I("bls:H720902", 100), I("ciqual:28845", 50),
         I("bls:G480100", 60), I("ciqual:11049", 6), I("ciqual:18066", 300), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(100, 170), serving_g=300),
 Recipe("zarzuela", "Zarzuela de pescado", "Сарсуэла",
        "fooddb editorial: Catalan fish stew — white fish with shrimp, mussel and squid in a "
        "tomato-wine broth; ~10 % evaporates",
        (I("bls:T204100", 150), I("bls:T753100", 80), I("bls:T792132", 80), I("ciqual:10001", 80),
         I("bls:G561100", 120), I("bls:G480100", 60), I("bls:P210000", 80), I("bls:Q120000", 20),
         I("ciqual:18066", 200), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(60, 110), serving_g=350),
 Recipe("migas", "Migas", "Мигас",
        "fooddb editorial: fried breadcrumbs with garlic and chorizo, topped with a fried egg",
        (I("bls:B821000", 200), I("ciqual:18066", 80), I("bls:G490100", 12), I("matvaretabellen:03.363", 80),
         I("bls:E111182", 60), I("bls:Q120000", 50), I("ciqual:11049", 4), I("ciqual:11017", 4)),
        cooked_yield=0.95, kcal_band=(300, 400), serving_g=200),
 Recipe("huevos-rellenos", "Huevos rellenos (stuffed eggs)", "Фаршированные яйца",
        "fooddb editorial: halved boiled eggs whose yolks are worked with tuna and mayonnaise",
        (I("bls:E111132", 200), I("bls:T121902", 80), I("ciqual:11054", 50), I("bls:G561100", 40)),
        cooked_yield=1.0, kcal_band=(170, 260), serving_g=120),
 Recipe("revuelto-setas", "Revuelto de setas (scrambled eggs with mushrooms)",
        "Ревуэльто с грибами",
        "fooddb editorial: soft-scrambled eggs with sautéed mushrooms and garlic",
        (I("bls:E111100", 200), I("bls:K701152", 150), I("bls:G490100", 5), I("bls:Q120000", 20),
         I("ciqual:11017", 3)),
        cooked_yield=0.95, kcal_band=(140, 200), serving_g=180),
 Recipe("carrillada", "Carrillada (braised pork cheek)", "Щёки в соусе",
        "fooddb editorial: pork cheeks braised in red wine with onion and carrot — pork shoulder "
        "stands in for the cheek; ~20 % evaporates",
        (I("bls:U632100", 300), I("bls:P253000", 150), I("bls:G480100", 80), I("bls:G620100", 60),
         I("bls:G490100", 5), I("ciqual:11053", 2), I("bls:Q120000", 15), I("ciqual:11017", 5)),
        cooked_yield=0.8, kcal_band=(150, 240), serving_g=250),
 Recipe("pollo-patatas", "Pollo con patatas", "Курица с картошкой",
        "fooddb editorial: chicken stewed with potato in tomato; ~10 % evaporates",
        (I("bls:V414100", 250), I("bls:K110100", 200), I("bls:G561100", 120), I("bls:G480100", 60),
         I("bls:Q120000", 20), I("ciqual:18066", 200), I("ciqual:11017", 5)),
        cooked_yield=0.9, kcal_band=(100, 160), serving_g=300),
 Recipe("macarrones-chorizo", "Macarrones con chorizo", "Макароны с чоризо",
        "fooddb editorial: pasta in a tomato-chorizo sauce — the boiled pasta takes up water",
        (I("bls:E401000", 150), I("matvaretabellen:03.363", 80), I("bls:G561100", 150), I("bls:R160000", 20),
         I("bls:G480100", 50), I("bls:Q120000", 20), I("ciqual:18066", 150), I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(140, 200), serving_g=300),
 Recipe("mejillones-escabeche", "Mejillones en escabeche", "Мидии в эскабече",
        "fooddb editorial: mussels pickled in oil, vinegar, paprika and bay; the marinade stays",
        (I("bls:T792132", 250), I("bls:Q120000", 60), I("ciqual:11220", 60), I("ciqual:11049", 5),
         I("ciqual:11053", 2), I("bls:G490100", 5), I("ciqual:11017", 4)),
        cooked_yield=1.0, kcal_band=(160, 240), serving_g=100),
 Recipe("bacalao-pilpil", "Bacalao al pil pil", "Бакалао аль пиль-пиль",
        "fooddb editorial: cod confit in olive oil with garlic and chili, the gelatine-thickened "
        "oil keeps",
        (I("bls:T204100", 300), I("bls:Q120000", 100), I("bls:G490100", 10), I("fdc:170106", 4)),
        cooked_yield=0.85, kcal_band=(240, 360), serving_g=180),
 Recipe("merluza-romana", "Merluza a la romana", "Мерлуза по-римски",
        "fooddb editorial: hake in egg-flour batter, fried; ~10 % lost, oil in",
        (I("bls:T209100", 300), I("bls:E111100", 60), I("bls:C214200", 40), I("bls:Q120000", 50),
         I("ciqual:11017", 4)),
        cooked_yield=0.85, kcal_band=(180, 270), serving_g=200),
 Recipe("pescaito-frito", "Pescaíto frito (Andalusian fried fish)", "Жареная рыба по-андалусски",
        "fooddb editorial: small fish floured and deep-fried; ~15 % lost, oil in",
        (I("bls:T213100", 300), I("bls:C214200", 40), I("bls:Q120000", 60), I("ciqual:11017", 4)),
        cooked_yield=0.85, kcal_band=(200, 290), serving_g=200),
 Recipe("flamenquin", "Flamenquín", "Фламенкин",
        "fooddb editorial: pork loin rolled around cured ham, breaded and deep-fried; ~15 % lost",
        (I("bls:U611100", 250), I("ciqual:28845", 80), I("bls:B821000", 50), I("bls:E111100", 40),
         I("bls:C214200", 30), I("bls:Q120000", 50), I("ciqual:11017", 4)),
        cooked_yield=0.85, kcal_band=(230, 330), serving_g=200),
 Recipe("cochinillo", "Cochinillo asado (roast suckling pig)", "Жареный молочный поросёнок",
        "fooddb editorial: milk-fed piglet roasted — the nearest table record is a fatty pork "
        "roast; the joint loses ~30 %",
        (I("bls:U571100", 500), I("bls:Q120000", 20), I("ciqual:11017", 8), I("bls:G490100", 5)),
        cooked_yield=0.7, kcal_band=(240, 360), serving_g=250),
 Recipe("montadito-lomo", "Montadito de lomo", "Монтадито с ломо",
        "fooddb editorial: a small roll with grilled pork loin",
        (I("bls:B511000", 60), I("bls:U611172", 60), I("bls:Q120000", 5)),
        cooked_yield=1.0, kcal_band=(220, 300), serving_g=120),
 Recipe("sandwich-vegetal", "Sándwich vegetal", "Овощной сэндвич",
        "fooddb editorial: the Spanish vegetable sandwich — white bread with lettuce, tomato, egg, "
        "tuna, olives and mayonnaise",
        (I("bls:B311000", 60), I("bls:G103100", 20), I("bls:G561100", 40), I("bls:E111132", 30),
         I("bls:T121902", 30), I("bls:H510802", 10), I("ciqual:11054", 20)),
        cooked_yield=1.0, kcal_band=(180, 260), serving_g=200),
 Recipe("alcachofas-jamon", "Alcachofas con jamón", "Артишоки с хамоном",
        "fooddb editorial: artichokes stewed with cured ham and garlic; ~10 % lost",
        (I("bls:G410132", 250), I("ciqual:28845", 60), I("bls:G490100", 5), I("bls:Q120000", 20),
         I("ciqual:5215", 40), I("ciqual:11017", 4)),
        cooked_yield=0.9, kcal_band=(80, 160), serving_g=200),
 Recipe("cuajada", "Cuajada (milk junket)", "Куахада",
        "fooddb editorial: ewe's-milk junket — milk set with rennet; modelled as whole milk, "
        "nothing is lost",
        (I("bls:M111300", 1000), I("bls:S111000", 15)),
        cooked_yield=1.0, kcal_band=(65, 85), serving_g=125),
 Recipe("ensaimada", "Ensaimada", "Энсаймада",
        "fooddb editorial: the Mallorcan lard pastry — a sugared, egged yeast dough worked with "
        "lard, baked; ~15 % lost",
        (I("bls:C214200", 250), I("bls:S111000", 80), I("bls:E111100", 50), I("bls:Q860000", 80),
         I("bls:M111300", 80), I("bls:R459000", 5), I("ciqual:11017", 3)),
        cooked_yield=0.85, kcal_band=(360, 450), serving_g=100),
 Recipe("membrillo", "Dulce de membrillo (quince paste)", "Айвовое повидло",
        "fooddb editorial: quince cooked down with its weight in sugar to a sliceable paste; ~40 % "
        "evaporates",
        (I("bls:F140100", 500), I("bls:S111000", 400), I("bls:F601600", 10)),
        cooked_yield=0.6, kcal_band=(280, 360), serving_g=30),
 Recipe("turron", "Turrón de Jijona (soft almond nougat)", "Туррон де Хихона",
        "fooddb editorial: ground almonds worked into cooked honey-sugar with egg white; the paste "
        "sets, nothing is lost",
        (I("fdc:170567", 350), I("bls:S121000", 250), I("bls:S111000", 150), I("bls:E113100", 40)),
        cooked_yield=0.97, kcal_band=(430, 550), serving_g=40),
 Recipe("polvorones", "Polvorones", "Польворонес",
        "fooddb editorial: the crumbly shortbread — flour, lard, sugar and ground almonds, baked; "
        "~10 % lost",
        (I("bls:C214200", 250), I("bls:Q860000", 120), I("bls:S111000", 80), I("bls:H120400", 60)),
        cooked_yield=0.9, kcal_band=(480, 600), serving_g=40),
 Recipe("pestinos", "Pestiños", "Пестиньос",
        "fooddb editorial: anise-sesame dough fried and glazed with honey; ~10 % out, oil and "
        "honey in",
        (I("bls:C214200", 200), I("bls:M111300", 80), I("bls:R459000", 3), I("fdc:170151", 10),
         I("bls:P7A1000", 10), I("bls:Q320000", 50), I("bls:S121000", 80), I("ciqual:11017", 2)),
        cooked_yield=0.9, kcal_band=(360, 480), serving_g=50),
 Recipe("tinto-verano", "Tinto de verano", "Тинто де верано",
        "fooddb editorial: red wine lengthened with carbonated lemonade, half and half",
        (I("bls:P253000", 120), I("bls:N310400", 120)),
        cooked_yield=1.0, kcal_band=(40, 70), serving_g=250),

 Recipe("ramen", "Ramen, shoyu", "Рамен с соевым соусом",
        "fooddb editorial: egg noodles in a hot broth with pork, a soft egg and soy — the noodles "
        "take up water",
        (I("bls:E432000", 150), I("ciqual:18066", 500), I("bls:U632100", 120), I("bls:E111132", 50),
         I("bls:R143000", 25), I("bls:G480100", 30), I("bls:K701100", 40), I("bls:R211200", 5),
         I("bls:Q230000", 5)),
        cooked_yield=1.0, kcal_band=(60, 110), serving_g=450),
 Recipe("poke", "Poke bowl", "Поке",
        "fooddb editorial: the bowl — sushi rice under raw salmon with soy, sesame, avocado and "
        "cucumber",
        (I("bls:C352032", 200), I("bls:T410100", 100), I("bls:R143000", 20), I("bls:Q230000", 8),
         I("bls:F502100", 60), I("bls:G520100", 50), I("bls:G480100", 20), I("fdc:170151", 5)),
        cooked_yield=1.0, kcal_band=(140, 200), serving_g=350),
 Recipe("roll-philadelphia", "Philadelphia roll", "Ролл «Филадельфия»",
        "fooddb editorial: sushi roll — rice, nori, salmon and cream cheese with cucumber; nothing "
        "is lost",
        (I("bls:C352032", 180), I("bls:G995000", 8), I("bls:T410100", 80), I("fdc:2705760", 50),
         I("bls:G520100", 30), I("bls:R121000", 5), I("bls:S111000", 5)),
        cooked_yield=1.0, kcal_band=(150, 210), serving_g=200),
 Recipe("buterbrod-maslo", "Bread with butter", "Бутерброд с маслом",
        "fooddb editorial: bread-and-butter — wheat-rye bread with butter, the same as a German "
        "Butterbrot",
        (I("bls:B251000", 50), I("bls:Q6A4000", 10)),
        cooked_yield=1.0, kcal_band=(300, 400), serving_g=60),


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
    uncomputable = {}
    for r in recipes:
        missing = [i.record for i in r.ingredients if not values.get(i.record)]
        if missing:
            # An ingredient never loaded or still pending: the recipe is skipped, loudly — it must
            # not vanish silently (see report() for the same list, readable).
            logger.warning(f"recipe {r.slug} skipped: no accepted values for {', '.join(missing)}")
            uncomputable[r.slug] = missing
            continue
        licence = max((meta[i.record]["licence"] for i in r.ingredients),
                      key=lambda lic: _rank(lic))
        found, _dropped = compute(r, values)
        flags = [OUTLIER_FLAG] if r.kcal_band and not r.kcal_band[0] <= found.get("ENERC_KCAL", 0) <= r.kcal_band[1] else []
        for suffix, name, lang in (("", r.name_en, "en"), (".ru", r.name_ru, "ru")):
            records.append(ingest.Record(
                id=f"recipe:{r.slug}{suffix}", source=SOURCE, layer="core", licence=licence,
                name=name, lang=lang, serving_g=r.serving_g, values=found, observed_at=at,
                categories=["recipe:dish"], extra_flags=list(flags), review_all=True, group=r.slug))
    foods = obs = 0
    if records:
        foods, obs = ingest.run(SOURCE, registry_ref(), records)
    return {"recipes": len(records) // 2, "skipped": len(uncomputable), "uncomputable": uncomputable,
            "foods": foods, "observations": obs} | _sweep(at)


def _sweep(at: datetime) -> dict:
    """Nothing pending or orphaned after a build. A recipe record whose slug left RECIPES is retired:
    its pending values are rejected and every nutrient it still serves is withdrawn by a null
    observation — the convention VALUES_SQL reads — so no orphan keeps serving. And only the newest
    values of a live recipe ever wait for review: an older pending row is rejected once a newer
    observation of the same nutrient exists."""
    live = {r.slug for r in RECIPES}
    with engine().begin() as conn:
        retired = sorted(conn.execute(text(
            "select id from food where id like 'recipe:%'")).scalars())
        retired = [i for i in retired if i.removeprefix("recipe:").removesuffix(".ru") not in live]
        if retired:
            conn.execute(text(
                "update observation set status = 'rejected', reviewed_by = :by, reviewed_at = now(), "
                "review_note = 'recipe retired' where status = 'pending' and food_id = any(:ids)"),
                {"by": REVIEWER, "ids": retired})
            conn.execute(text(WITHDRAW_SQL), {"by": REVIEWER, "ids": retired, "at": at})
        superseded = conn.execute(text(
            "update observation o set status = 'rejected', reviewed_by = :by, reviewed_at = now(), "
            "review_note = :note where o.food_id like 'recipe:%' and o.status = 'pending' and exists ("
            "select 1 from observation n where n.food_id = o.food_id and n.nutrient = o.nutrient "
            "and (n.observed_at, n.id) > (o.observed_at, o.id))"),
            {"by": REVIEWER, "note": f"superseded by recipe rebuild {registry_ref()}"}).rowcount
    return {"retired": retired, "superseded": superseded}


# For each nutrient a retired record still serves (its newest accepted value is not null), store a
# newer accepted null — the same withdrawal ingest writes when a source drops a field.
WITHDRAW_SQL = """
insert into observation (food_id, nutrient, value_per_100, unit, basis, status, source, licence,
                         observed_at, reviewed_by, reviewed_at, review_note)
select food_id, nutrient, null, unit, basis, 'accepted', source, licence,
       :at, :by, now(), 'recipe retired'
from (select distinct on (food_id, nutrient) food_id, nutrient, unit, basis, source, licence, value_per_100
      from observation where food_id = any(:ids) and status = 'accepted'
      order by food_id, nutrient, observed_at desc, id desc) newest
where value_per_100 is not null
"""


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
