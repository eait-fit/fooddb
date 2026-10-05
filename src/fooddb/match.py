"""Product matching: Splink decides which source records describe the same product.

Every record takes part, barcoded or not; the barcode is a strong feature, not a rule. Pairs at or
above the threshold merge automatically: the lower product id survives, the others point at it
(`product.merged_into`) and their records move over. Nothing is ever split again by matching.

The m/u probabilities are set by hand rather than trained, so results are deterministic on any
data size. ponytail: hand-set weights and a full re-match per run; train on labelled pairs and match
only new records once volume makes this slow.
"""

import os
import re

import pyarrow as pa
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
from sqlalchemy import text

from fooddb.db import engine

THRESHOLD = float(os.environ.get("FOODDB__BACKEND__MATCH_THRESHOLD", "0.95"))

RECORDS_SQL = """
select f.id as unique_id, f.product_id, f.gtin14, f.name, f.brand, f.lang,
       max(v.value) filter (where v.nutrient = 'ENERC_KCAL') as kcal,
       max(v.value) filter (where v.nutrient = 'PROCNT') as protein,
       max(v.value) filter (where v.nutrient = 'FAT') as fat,
       max(v.value) filter (where v.nutrient = 'CHOCDF') as carbs,
       max(v.value) filter (where v.nutrient = 'NA') as sodium
from food f
left join lateral (
    select distinct on (nutrient) nutrient, value_per_100::float as value
    from observation o
    where o.food_id = f.id and o.status = 'accepted'
    order by nutrient, observed_at desc, id desc
) v on true
group by f.id
"""


def _tokens(s: str | None) -> list[str]:
    return re.findall(r"[^\W_]+", (s or "").lower())


def _prepare(row: dict) -> dict:
    """Brand words out of the name, words sorted: "ACME, HUMMUS CLASSIC" ≈ "Hummus Classic"."""
    brand = set(_tokens(row["brand"]))
    words = [t for t in _tokens(row["name"]) if t not in brand] or _tokens(row["name"])
    return row | {
        "name_norm": " ".join(sorted(set(words))),
        "name_words": sorted(set(words)),
        "name_key": words[0] if words else None,
        "brand": " ".join(sorted(brand)) or None,
        "kcal_band": int(row["kcal"] // 25) if row["kcal"] is not None else None,
    }


def _near(col: str, rel: float, abs_: float) -> str:
    return f"abs({col}_l - {col}_r) <= {rel} * greatest({col}_l, {col}_r) + {abs_}"


# Word overlap, not character similarity: "bell peppers raw red" vs "... yellow" differ by the one
# word that makes them different foods, which Jaro-Winkler on a long name barely notices.
_JACCARD = ("len(list_intersect(name_words_l, name_words_r)) * 1.0"
            " / len(list_distinct(list_concat(name_words_l, name_words_r)))")

NAME = cl.CustomComparison(
    output_column_name="name_words",
    comparison_levels=[
        {"sql_condition": "name_words_l is null or name_words_r is null or len(name_words_l) = 0 or len(name_words_r) = 0",
         "label_for_charts": "null", "is_null_level": True},
        {"sql_condition": "name_norm_l = name_norm_r", "label_for_charts": "same words"},
        {"sql_condition": f"{_JACCARD} >= 0.8", "label_for_charts": "words overlap >= 0.8"},
        {"sql_condition": f"{_JACCARD} >= 0.6", "label_for_charts": "words overlap >= 0.6"},
        {"sql_condition": "else", "label_for_charts": "else"},
    ],
).configure(m_probabilities=[0.6, 0.25, 0.1, 0.05], u_probabilities=[5e-5, 2e-3, 1e-2, 0.98795])


NUTRIENT_COLS = ("kcal", "protein", "fat", "carbs", "sodium")


def _all_near(rel: float, abs_: float) -> str:
    # A field missing on either side neither helps nor hurts.
    return " and ".join(f"({c}_l is null or {c}_r is null or {_near(c, rel, abs_)})" for c in NUTRIENT_COLS)


# ONE comparison for all nutrients, not one each: they are not independent (generic variants share
# whole vectors), and counting each agreement separately let identical numbers outvote the name.
NUTRIENTS = cl.CustomComparison(
    output_column_name="nutrients",
    comparison_levels=[
        {"sql_condition": "kcal_l is null or kcal_r is null", "label_for_charts": "null", "is_null_level": True},
        {"sql_condition": _all_near(0.03, 1), "label_for_charts": "all within 3%"},
        {"sql_condition": _all_near(0.10, 2), "label_for_charts": "all within 10%"},
        {"sql_condition": "else", "label_for_charts": "else"},
    ],
).configure(m_probabilities=[0.7, 0.2, 0.1], u_probabilities=[0.005, 0.05, 0.945])


SETTINGS = SettingsCreator(
    link_type="dedupe_only",
    unique_id_column_name="unique_id",
    probability_two_random_records_match=3e-5,
    # Candidate pairs only: same barcode; same name words at similar energy; or same brand and first
    # word at similar energy. A bare name word ("chocolate") would compare every pair of a block
    # with tens of thousands of OFF products.
    blocking_rules_to_generate_predictions=[
        block_on("gtin14"),
        block_on("name_norm", "kcal_band"),
        block_on("name_key", "brand", "kcal_band"),
    ],
    comparisons=[
        # Two different GTINs are, by GS1's definition, two trade items (flavours, sizes): strong
        # evidence against, which names and nutrients alone must not outvote.
        cl.ExactMatch("gtin14").configure(m_probabilities=[0.999, 0.001], u_probabilities=[1e-5, 1 - 1e-5]),
        NAME,
        # Branded vs generic is its own level: a brand's product is not the generic food it resembles.
        cl.CustomComparison(
            output_column_name="brand",
            comparison_levels=[
                {"sql_condition": "brand_l is null and brand_r is null", "label_for_charts": "both generic",
                 "is_null_level": True},
                {"sql_condition": "brand_l = brand_r", "label_for_charts": "same brand"},
                {"sql_condition": "brand_l is null or brand_r is null", "label_for_charts": "branded vs generic"},
                {"sql_condition": "else", "label_for_charts": "different brands"},
            ],
        ).configure(m_probabilities=[0.7, 0.05, 0.25], u_probabilities=[0.01, 0.3, 0.69]),
        NUTRIENTS,
    ],
    retain_intermediate_calculation_columns=False,
)


def clusters(rows: list[dict], threshold: float = THRESHOLD) -> list[list[str]]:
    """Groups of record ids (size > 1) that describe the same product."""
    if len(rows) < 2:
        return []
    db = DuckDBAPI()
    linker = Linker(db.register(pa.Table.from_pylist([_prepare(r) for r in rows])), SETTINGS, log_level=30)
    predictions = linker.inference.predict(threshold_match_probability=threshold, warning_mode="never")
    found = linker.clustering.cluster_pairwise_predictions_at_threshold(predictions, threshold).as_record_list()
    groups: dict[str, list[str]] = {}
    for r in found:
        groups.setdefault(r["cluster_id"], []).append(r["unique_id"])
    return [ids for ids in groups.values() if len(ids) > 1]


def run(threshold: float = THRESHOLD) -> int:
    """Match every record; merge products that matched. Returns how many products were merged away."""
    with engine().connect() as conn:
        rows = [dict(r) for r in conn.execute(text(RECORDS_SQL)).mappings()]
    product_of = {r["unique_id"]: r["product_id"] for r in rows}
    merged = 0
    with engine().begin() as conn:
        for ids in clusters(rows, threshold):
            pids = sorted({product_of[i] for i in ids})
            survivor, others = pids[0], pids[1:]
            if not others:
                continue
            conn.execute(text("update food set product_id = :s where product_id = any(:o)"), {"s": survivor, "o": others})
            conn.execute(text("update product set merged_into = :s where id = any(:o)"), {"s": survivor, "o": others})
            merged += len(others)
    return merged
