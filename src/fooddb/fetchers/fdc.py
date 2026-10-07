"""USDA FoodData Central bulk JSON (CC0): Foundation Foods (twice a year), SR Legacy (frozen, 7.8k foods)
and Branded Foods (twice a year, about 3 GB of JSON, read as a stream)."""

import re
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx

from fooddb import gtin, ingest
from fooddb.fetchers import download, json_items

LISTING = "https://fdc.nal.usda.gov/download-datasets.html"
BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
# dataset → (file name stem, top-level JSON key)
DATASETS = {
    "foundation": ("foundation_food_json", "FoundationFoods"),
    "sr_legacy": ("sr_legacy_food_json", "SRLegacyFoods"),
    "branded": ("branded_food_json", "BrandedFoods"),
}

# FDC nutrient id → INFOODS tagname. Energy: 1008 when present, else Atwater general (2047).
# 1005 is carbohydrate by difference, fibre included. FDC reports no available carbohydrate.
# 1018 is "Alcohol, ethyl" in g.
NUTRIENTS = {
    1003: "PROCNT", 1004: "FAT", 1005: "CHOCDF", 2000: "SUGAR",
    1258: "FASAT", 1079: "FIBTG", 1093: "NA", 1062: "ENERC_KJ", 1018: "ALC",
}
ENERGY = (1008, 2047)


def latest_release(dataset: str) -> str:
    r = httpx.get(LISTING, timeout=60, follow_redirects=True)
    r.raise_for_status()
    found = set(re.findall(rf"FoodData_Central_{DATASETS[dataset][0]}_[\d-]+\.zip", r.text))
    if not found:
        raise RuntimeError(f"fdc: no {dataset} release linked from {LISTING}; the page layout changed")
    return max(found)


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def records(foods: Iterable[dict]):
    """One record per FDC food. A branded food also has its barcode, brand owner and label serving.
    Its values are per 100 ml when its serving is in ml."""
    for f in filter(None, foods):
        by_id = {
            n["nutrient"]["id"]: n.get("amount")
            for n in f.get("foodNutrients") or []
            if n and (n.get("nutrient") or {}).get("id") is not None
        }
        values = {tag: float(by_id[i]) for i, tag in NUTRIENTS.items() if by_id.get(i) is not None}
        kcal = next((by_id[i] for i in ENERGY if by_id.get(i) is not None), None)
        if kcal is not None:
            values["ENERC_KCAL"] = float(kcal)
        if not values:
            continue
        published = f.get("publicationDate") or "2000-01-01"
        unit = (f.get("servingSizeUnit") or "").lower()
        categories = [(f.get("foodCategory") or {}).get("description"), f.get("brandedFoodCategory")]
        yield ingest.Record(
            id=f"fdc:{f['fdcId']}", source="fdc", layer="core", licence="CC0-1.0",
            name=f["description"], lang="en", values=values, basis="100ml" if unit in ("ml", "mlt") else "100g",
            gtin14=gtin.normalize(f.get("gtinUpc")), brand=f.get("brandOwner") or None,
            serving_text=f.get("householdServingFullText") or None,
            serving_g=_num(f.get("servingSize")) if unit in ("g", "grm") else None,
            categories=[c for c in categories if c],
            observed_at=datetime.strptime(published, "%m/%d/%Y" if "/" in published else "%Y-%m-%d").replace(tzinfo=UTC),
        )


def fetch(dataset: str = "foundation", force: bool = False) -> tuple[int, int] | None:
    release = latest_release(dataset)
    fetcher = f"fdc-{dataset}"
    if not force and ingest.already_done(fetcher, release):
        return None
    with tempfile.TemporaryFile() as tmp:  # the zip goes to disk, not memory
        download(BASE + release, tmp)
        with zipfile.ZipFile(tmp) as z, z.open(next(n for n in z.namelist() if n.endswith(".json"))) as f:
            return ingest.run(fetcher, release, records(json_items(f, DATASETS[dataset][1])))
