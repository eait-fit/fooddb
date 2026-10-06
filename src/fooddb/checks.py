"""Automatic checks run on every incoming record. They flag, they never fix.

Also the rules the checks read: source categories onto fooddb categories, plausible ranges per
category, and the front-of-pack warning seals that values imply.
"""

from collections.abc import Callable, Iterable, Mapping

# Source category → fooddb category. The first row with a tag the record carries wins, so a narrow
# tag comes before its parent (OFF tags carry every ancestor). Tags: OFF `categories_tags`, FDC
# `foodCategory.description` and `brandedFoodCategory`, and for the national tables
# "<source>:<group>": CIQUAL group names, Fineli use classes, Matvaretabellen food group ids and MEXT food
# group numbers. A None row stops the search: no category, so no range check.
CATEGORIES: list[tuple[str | None, tuple[str, ...]]] = [
    ("alcoholic-beverages", ("en:alcoholic-beverages", "ciqual:alcoholic beverages", "fineli:ALCTOT",
                             "matvaretabellen:9.3")),
    # Concentrates, powders, sprays and cooking creams: as sold, they are not what the category's ranges describe.
    (None, ("en:syrups", "en:beverage-preparations", "en:dehydrated-beverages", "en:instant-beverages",
            "en:coconut-milks", "en:coconut-creams", "en:meal-replacements", "en:dietary-supplements",
            "en:olive-oil-sprays", "Powdered Drinks", "Liquid Water Enhancer", "Herbal Supplements",
            "Weight Control", "ciqual:beverages, to reconstitute", "fineli:MEALREP", "fineli:SPECSUPP",
            "matvaretabellen:10.10")),
    ("beverages", ("en:flavored-carbonated-mineral-waters",)),
    ("waters", ("en:spring-waters", "fineli:DRWATER")),  # OFF files mineral waters under spring waters
    # FDC Branded files sweetened sparkling waters under "Water".
    ("beverages", ("en:beverages", "Beverages", "Water", "Soda", "Fruit & Vegetable Juice, Nectars & Fruit Drinks",
                   "ciqual:beverages", "fineli:BEVTOT", "matvaretabellen:9", "mext:16")),
    ("oils", ("en:vegetable-oils", "en:fish-oils", "ciqual:vegetable oils", "ciqual:fish oils",
              "matvaretabellen:8.2")),
    ("fats", ("en:fats", "Fats and Oils", "ciqual:fats and oils", "fineli:FATTOT", "matvaretabellen:8", "mext:14")),
    ("dairy", ("en:dairies", "Dairy and Egg Products", "Cheese", "Milk", "Yogurt", "ciqual:milk and milk products",
               "fineli:MILKDTOT", "matvaretabellen:1", "mext:13")),
    ("vegetables", ("en:fresh-vegetables", "en:frozen-vegetables", "en:canned-vegetables",
                    "Vegetables and Vegetable Products", "Canned Vegetables", "Frozen Vegetables",
                    "ciqual:vegetables", "fineli:VEGFRESH", "matvaretabellen:6.2", "mext:06")),
    ("fruits", ("en:fresh-fruits", "Fruits and Fruit Juices", "Canned Fruit", "ciqual:fruits", "fineli:FRUFRESH",
                "fineli:BERFRESH", "matvaretabellen:13.1", "matvaretabellen:13.2", "mext:07")),
    ("legumes", ("en:legumes-and-their-products", "Legumes and Legume Products", "ciqual:legumes",
                 "matvaretabellen:12", "mext:04")),
    ("nuts", ("en:nuts-and-their-products", "Nut and Seed Products", "Nut & Seed Butters", "ciqual:nuts and seeds",
              "matvaretabellen:14", "mext:05")),
    ("cereals", ("en:cereal-grains", "en:pastas", "Cereal Grains and Pasta", "Rice", "Pasta by Shape & Type",
                 "ciqual:pasta, rice and grains", "ciqual:flours", "fineli:RICEADD", "fineli:PASTAADD",
                 "matvaretabellen:5.1", "matvaretabellen:5.2")),
    ("meat", ("en:meats-and-their-products", "Beef Products", "Pork Products", "Poultry Products",
              "Lamb, Veal, and Game Products", "Sausages and Luncheon Meats", "Pepperoni, Salami & Cold Cuts",
              "Sausages, Hotdogs & Brats", "ciqual:cooked meat", "ciqual:raw meat", "ciqual:delicatessen meat and similar",
              "fineli:MSTEAK", "fineli:SAUSAGE", "matvaretabellen:3", "mext:11")),
    ("fish", ("en:fishes-and-their-products", "en:seafood", "Finfish and Shellfish Products", "Fish & Seafood",
              "Canned Tuna", "ciqual:fish, cooked", "ciqual:fish, raw", "ciqual:seafood, cooked", "ciqual:seafood, raw",
              "fineli:FISH", "matvaretabellen:4", "mext:10")),
    ("sweets", ("en:sweet-snacks", "Sweets", "Candy", "ciqual:sugar and confectionery", "fineli:SUGARTOT",
                "matvaretabellen:7", "mext:03", "mext:15")),
    ("snacks", ("en:salty-snacks", "Snacks", "Chips, Pretzels & Snacks", "fineli:SNACK", "matvaretabellen:10.5")),
]

# Plausible values per 100 g or 100 ml: (category, basis or None for both, field, low, high), None
# for an open bound. Conservative on purpose: a value out of range waits for review, so a row flags
# only what no real product of the category has.
RANGES: list[tuple[str, str | None, str, float | None, float | None]] = [
    # FDC SR Legacy "Oil, olive, salad or cooking": 100 g fat per 100 g. At about 0.92 g/ml, 92 g per 100 ml.
    ("oils", None, "FAT", 85, 100),
    # Natural mineral water has no energy. EU 1169/2011 Annex V exempts waters from the nutrition declaration.
    ("waters", None, "ENERC_KCAL", None, 5),
    ("waters", None, "SUGAR", None, 1),
    # Ready to drink. Whole milk has 61 kcal, cola about 42 kcal per 100 ml (FDC SR Legacy). Room for
    # shakes and smoothies. Per 100 g, beverages include powders, so no bound.
    ("beverages", "100ml", "ENERC_KCAL", None, 150),
    # FDC SR Legacy "Avocados, raw, all commercial varieties": 14.7 g fat, the fattiest common fruit.
    ("fruits", None, "FAT", None, 30),
    # Plain vegetables are low in fat. Frozen fries and vegetables packed in oil stay under 20 g.
    ("vegetables", None, "FAT", None, 30),
    # FDC SR Legacy "Rice bran, crude": 20.9 g fat, the fattiest cereal product. Fried instant noodles: about 20 g.
    ("cereals", None, "FAT", None, 30),
]


class _Reads(dict):
    """The values, recording which ones a rule reads. A missing one raises KeyError: the rule cannot say."""

    def __init__(self, values: Mapping[str, float]):
        super().__init__(values)
        self.read: set[str] = set()

    def __getitem__(self, key: str) -> float:
        self.read.add(key)
        return super().__getitem__(key)


Rule = Callable[[_Reads, bool], bool]  # (values, liquid) → does the product carry the seal


def _over(field: str, solid: float, liquid: float) -> Rule:
    return lambda v, liq: v[field] > (liquid if liq else solid)


def _at_least(field: str, solid: float, liquid: float) -> Rule:
    return lambda v, liq: v[field] >= (liquid if liq else solid)


def _energy_share(field: str, kcal_per_g: float, share: float) -> Rule:
    return lambda v, _liq: 0 < share * v["ENERC_KCAL"] <= kcal_per_g * v[field]


# Front-of-pack warning seals per scheme, per 100 g of a solid or 100 ml of a liquid. The schemes
# count added sugars, fats or sodium only, and exempt some foods. fooddb knows total values only, so
# a computed seal is an upper bound on the label.
SEALS: dict[str, dict[str, Rule]] = {
    # Chile: Ley 20.606, Reglamento Sanitario de los Alimentos art. 120 bis (Decreto 13/2015), limits
    # in force since 27 June 2019. A seal when the value is over the limit.
    "CL": {
        "calories": _over("ENERC_KCAL", 275, 70),
        "sugars": _over("SUGAR", 10, 5),
        "saturated-fat": _over("FASAT", 4, 3),
        "sodium": _over("NA", 400, 100),
    },
    # Mexico: NOM-051-SCFI/SSA1-2010 as modified in the DOF on 27 March 2020, nutrient profile, phase 3
    # (from 1 October 2025). Sugars count free sugars on the label; fooddb has total sugars.
    "MX": {
        "calories": lambda v, liq: v["ENERC_KCAL"] >= 70 or 4 * v["SUGAR"] >= 8 if liq else v["ENERC_KCAL"] >= 275,
        "sugars": _energy_share("SUGAR", 4, 0.10),
        "saturated-fat": _energy_share("FASAT", 9, 0.10),
        # 1 mg sodium per kcal, or 300 mg. A non-caloric drink: 45 mg.
        "sodium": lambda v, liq: v["NA"] >= 300 or (v["NA"] >= 45 if liq and v["ENERC_KCAL"] < 4
                                                    else v["NA"] >= v["ENERC_KCAL"]),
    },
    # Peru: Ley 30021, Manual de Advertencias Publicitarias (DS 012-2018-SA), phase 2 limits in force
    # since 17 September 2021. A seal at or over the limit. No energy seal.
    "PE": {
        "sugars": _at_least("SUGAR", 10, 5),
        "saturated-fat": _at_least("FASAT", 4, 3),
        "sodium": _at_least("NA", 400, 100),
    },
}

# OFF `labels_tags` for a seal printed on the pack, without the language prefix.
STATED_SEALS = {
    "high-in-calories-chile-ministry-of-health": ("CL", "calories"),
    "high-in-sugars-chile-ministry-of-health": ("CL", "sugars"),
    "high-in-saturated-fats-chile-ministry-of-health": ("CL", "saturated-fat"),
    "high-in-sodium-chile-ministry-of-health": ("CL", "sodium"),
    "exceso-calorias": ("MX", "calories"),
    "exceso-azucares": ("MX", "sugars"),
    "exceso-grasas-saturadas": ("MX", "saturated-fat"),
    "exceso-sodio": ("MX", "sodium"),
}


def category(tags: Iterable[str]) -> str | None:
    tags = set(tags)
    return next((cat for cat, row in CATEGORIES if tags.intersection(row)), None)


def _seal(rule: Rule, values: Mapping[str, float], liquid: bool) -> tuple[bool | None, set[str]]:
    v = _Reads(values)
    try:
        return rule(v, liquid), v.read
    except KeyError:
        return None, set()


def seals(values: Mapping[str, float], liquid: bool) -> tuple[dict[str, dict[str, bool]], set[str]]:
    """Per scheme, each seal the values decide (True: the product carries it), and the fields read.
    A seal whose inputs are missing is left out."""
    out: dict[str, dict[str, bool]] = {}
    used: set[str] = set()
    for scheme, rules in SEALS.items():
        for name, rule in rules.items():
            carried, read = _seal(rule, values, liquid)
            if carried is not None:
                out.setdefault(scheme, {})[name] = carried
                used |= read
    return out, used


def flags(values: Mapping[str, float], category: str | None = None, basis: str = "100g",
          labels: Iterable[str] = ()) -> dict[str, set[str]]:
    """Values are per 100 g, keyed by INFOODS tagname. Each failed check names the fields it implicates.

    Carbohydrate is CHOCDF (by difference, fibre included) or CHOAVL (available, fibre excluded),
    whichever the record has. With CHOAVL, Atwater adds fibre at 2 kcal/g (EU 1169/2011 Annex XIV).
    """
    out: dict[str, set[str]] = {}
    carbs = "CHOAVL" if "CHOAVL" in values else "CHOCDF"
    macros = ("PROCNT", "FAT", carbs)
    kcal = values.get("ENERC_KCAL")
    p, f, c = values.get("PROCNT"), values.get("FAT"), values.get(carbs)
    fibre = values.get("FIBTG") if carbs == "CHOAVL" else None
    if kcal is not None and None not in (p, f, c):
        atwater = 4 * p + 9 * f + 4 * c + 2 * (fibre or 0)
        if abs(kcal - atwater) > max(20, 0.25 * max(kcal, atwater)):
            out["energy-mismatch"] = {"ENERC_KCAL", *macros} | ({"FIBTG"} if fibre is not None else set())
    if sum(v for v in (p, f, c) if v is not None) > 105:
        out["macros-over-100g"] = {k for k in macros if k in values}
    sugar, sat = values.get("SUGAR"), values.get("FASAT")
    if sugar is not None and c is not None and sugar > c + 0.5:
        out["sugars-over-carbs"] = {"SUGAR", carbs}
    if sat is not None and f is not None and sat > f + 0.5:
        out["saturates-over-fat"] = {"FASAT", "FAT"}
    if negative := {k for k, v in values.items() if v < 0}:
        out["negative-value"] = negative
    if out_of_range := {
        field for cat, b, field, lo, hi in RANGES
        if cat == category and b in (None, basis) and field in values
        and not ((lo is None or values[field] >= lo) and (hi is None or values[field] <= hi))
    }:
        out["out-of-range"] = out_of_range
    # A seal on the pack that the values do not reach. The other way round says nothing: OFF lists labels incompletely.
    for tag in labels:
        if stated := STATED_SEALS.get(tag.split(":", 1)[-1]):
            scheme, name = stated
            carried, read = _seal(SEALS[scheme][name], values, basis == "100ml")
            if carried is False:
                out.setdefault("seal-disagreement", set()).update(read)
    return out
