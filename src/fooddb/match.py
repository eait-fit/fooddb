"""Product matching: Splink decides which source records describe the same product.

Every record takes part, barcoded or not; the barcode is a strong feature, not a rule. Pairs at or
above the threshold merge automatically: the lower product id survives, the others point at it
(`product.merged_into`) and their records move over. Each merge is logged in `merge_log`. A split
(`review.split`) writes `cannot_link` pairs, and matching never joins such a pair again.

The m/u probabilities are hand-set (`SETTINGS`) until `fooddb match train` saves a model estimated
on the data to FOODDB__BACKEND__MATCH_MODEL. ponytail: a full re-match per run; match only new
records once volume makes this slow.
"""

import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
from sqlalchemy import text

from fooddb import dump
from fooddb.db import engine, merge_log

THRESHOLD = float(os.environ.get("FOODDB__BACKEND__MATCH_THRESHOLD", "0.95"))
# Records per Arrow batch streamed into DuckDB. The job used to materialise the whole candidate
# set as Python dicts — twice (raw and prepared) — and at ~3 M rows that was most of a ~4 GB peak
# on a box the worker shares; the kernel killed the task every night.
LOAD_BATCH = 100_000
# The linker engine's own budget: what a join or an aggregate cannot hold it spills to the temp
# dir instead of growing the task's RSS. The production box shares ~8 GB between the API,
# Postgres and the rest of the stack — the uncapped engine is what took the task past 4 GB.
MEMORY_LIMIT = os.environ.get("FOODDB__BACKEND__MATCH_MEMORY_LIMIT", "1500MB")
# RECORDS_SQL's output plus what _prepare adds: the schema a record lands in DuckDB with. Fixed
# rather than inferred because a batch whose column is all null would type it `null` differently
# from its neighbours.
SCHEMA = pa.schema([
    ("unique_id", pa.string()), ("product_id", pa.int64()), ("gtin14", pa.string()),
    ("name", pa.string()), ("brand", pa.string()), ("lang", pa.string()),
    ("kcal", pa.float64()), ("protein", pa.float64()), ("fat", pa.float64()),
    ("carbs", pa.float64()), ("sodium", pa.float64()),
    ("name_norm", pa.string()), ("name_words", pa.list_(pa.string())), ("name_key", pa.string()),
    ("kcal_band", pa.int64()),
])

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
where f.source <> 'recipe'  -- a recipe is its own product by construction (its name records share one);
                            -- merging it into a branded or crowd record would bury its reviewed values
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


def model() -> SettingsCreator | str:
    """The trained model when one is saved, else the hand-set weights."""
    path = os.environ.get("FOODDB__BACKEND__MATCH_MODEL")
    return path if path and os.path.exists(path) else SETTINGS


def _linker(records, settings: SettingsCreator | str, workdir: Path) -> Linker:
    """`records` is a RecordBatchReader (the catalogue streamed in) or a small list of record
    dicts in tests. Two bounds on the job's RSS: a reader drains on its first scan and Splink
    scans its input more than once, so the stream is materialised once into a real table whose
    name the linker gets; and the engine is file-backed in `workdir`, so its tables live on disk
    and `memory_limit` caps only the working set, which spills instead of growing."""
    api = DuckDBAPI(connection=str(workdir / "match.duckdb"))
    api.duckdb_con.execute(f"set memory_limit = '{MEMORY_LIMIT}'")
    api.duckdb_con.execute("set preserve_insertion_order = false")
    api.duckdb_con.execute(f"set temp_directory = '{workdir / 'spill'}'")
    if isinstance(records, pa.RecordBatchReader):
        api.duckdb_con.register("_stream", records)
        api.duckdb_con.execute("create table catalogue as select * from _stream")
        table = api.register("catalogue")
    else:
        table = api.register(pa.Table.from_pylist([_prepare(r) for r in records], schema=SCHEMA))
    return Linker(table, settings, log_level=30)


def _workdir() -> tempfile.TemporaryDirectory:
    """Scratch space under the dumps volume (FOODDB__BACKEND__DUMP_DIR), not the system temp:
    the prod worker's /tmp is a 512MB tmpfs, and the DuckDB file plus its spill need real disk."""
    parent = dump.directory() / "match-work"
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="fooddb-match-", dir=parent)


def _records() -> Iterator[dict]:
    with engine().connect() as conn:
        # yield_per as an execution option turns on a server-side cursor (it becomes
        # stream_results + a row buffer at execute). Result.yield_per() after execute would
        # only batch iteration over a result psycopg already buffered whole.
        result = conn.execution_options(yield_per=LOAD_BATCH).execute(text(RECORDS_SQL))
        for r in result.mappings():
            yield dict(r)


def _record_reader() -> pa.RecordBatchReader:
    """The catalogue as a lazy Arrow stream: DuckDB pulls a batch at a time as it materialises its
    input table, so the records never coexist as Python objects."""
    def batches() -> Iterator[pa.RecordBatch]:
        buf: list[dict] = []
        for r in _records():
            buf.append(_prepare(r))
            if len(buf) >= LOAD_BATCH:
                yield pa.RecordBatch.from_pylist(buf, schema=SCHEMA)
                buf.clear()
        if buf:
            yield pa.RecordBatch.from_pylist(buf, schema=SCHEMA)
    return pa.RecordBatchReader.from_batches(SCHEMA, batches())


def links(records, threshold: float = THRESHOLD) -> list[tuple[str, str, float]]:
    """Record pairs at or above the threshold, with their match probability."""
    if not isinstance(records, pa.RecordBatchReader) and len(records) < 2:
        return []
    with _workdir() as workdir:
        predictions = _linker(records, model(), Path(workdir)).inference.predict(
            threshold_match_probability=threshold, warning_mode="never")
        # Only the three columns merges() needs, straight out of DuckDB: as_record_list() would
        # materialise every comparison column of every pair as a dict.
        rows = predictions.db_api.duckdb_con.sql(
            f"select unique_id_l, unique_id_r, match_probability from {predictions.physical_name}"
        ).fetchall()
        return [(a, b, float(p)) for a, b, p in rows]


def merges(product_of: dict[str, int], links: list[tuple[str, str, float]],
           cannot: list[tuple[str, str]]) -> dict[int, list[tuple[int, float]]]:
    """Survivor -> [(merged product, probability)]: the connected components of the links over
    products, strongest link first. A link that would put both records of a cannot-link pair in one
    product is skipped, so a component splits along the constraint at its weakest links."""
    parent: dict[int, int] = {}

    def find(p: int) -> int:
        while parent.get(p, p) != p:
            p = parent[p]
        return p

    forbid: dict[int, set[int]] = {}
    for a, b in cannot:
        pa, pb = product_of.get(a), product_of.get(b)
        if pa is not None and pb is not None and pa != pb:
            forbid.setdefault(pa, set()).add(pb)
            forbid.setdefault(pb, set()).add(pa)
    best: dict[int, float] = {}
    for a, b, prob in sorted(links, key=lambda link: (-link[2], link[0], link[1])):
        pa, pb = product_of[a], product_of[b]
        ra, rb = sorted((find(pa), find(pb)))
        if ra == rb or any(find(x) == ra for x in forbid.get(rb, ())):
            continue
        parent[rb] = ra
        forbid[ra] = forbid.get(ra, set()) | forbid.pop(rb, set())
        for p in (pa, pb):
            best[p] = max(best.get(p, 0.0), prob)
    out: dict[int, list[tuple[int, float]]] = {}
    for p in sorted(best):
        if find(p) != p:
            out.setdefault(find(p), []).append((p, best[p]))
    return out


def run(threshold: float = THRESHOLD) -> int:
    """Match every record; merge products that matched. Returns how many products were merged away."""
    pairs = links(_record_reader(), threshold)
    ids = {a for a, _, _ in pairs} | {b for _, b, _ in pairs}
    with engine().connect() as conn:
        cannot = [tuple(r) for r in conn.execute(text("select food_a, food_b from cannot_link"))]
        for a, b in cannot:
            ids.update((a, b))
        # Product ids for the linked and cannot-link records only, read AFTER linking so it is one
        # lookup per linked record instead of one per catalogue record — the second big resident
        # set. Nothing here writes product ids, so the delay cannot make the read stale.
        product_of = dict(conn.execute(
            text("select id, product_id from food where id = any(:ids)"), {"ids": list(ids)}).all())
    merged = 0
    with engine().begin() as conn:
        for survivor, others in merges(product_of, pairs, cannot).items():
            for pid, prob in others:
                moved = conn.execute(text("update food set product_id = :s where product_id = :o returning id"),
                                     {"s": survivor, "o": pid}).scalars().all()
                conn.execute(text("update product set merged_into = :s where id = :o"), {"s": survivor, "o": pid})
                conn.execute(merge_log.insert().values(kind="merge", from_product=pid, into_product=survivor,
                                                       food_ids=sorted(moved), probability=prob, threshold=threshold))
                merged += 1
    return merged


def train(path: str) -> dict:
    """Estimate u by random sampling and m by EM on the current records; save the model as JSON."""
    with _workdir() as workdir:
        linker = _linker(_record_reader(), SETTINGS, Path(workdir))
        linker.training.estimate_u_using_random_sampling(max_pairs=1e7, seed=1)
        for rule in (block_on("gtin14"), block_on("name_norm", "kcal_band")):
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
        return linker.misc.save_model_to_json(path, overwrite=True)
