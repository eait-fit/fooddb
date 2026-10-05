"""USDA FoodData Central bulk JSON (CC0): Foundation Foods (twice a year) and SR Legacy (frozen, 7.8k foods)."""

import json
import re
import tempfile
import zipfile
from datetime import UTC, datetime

import httpx

from fooddb import ingest

LISTING = "https://fdc.nal.usda.gov/download-datasets.html"
BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
# dataset → (file name stem, top-level JSON key)
DATASETS = {
    "foundation": ("foundation_food_json", "FoundationFoods"),
    "sr_legacy": ("sr_legacy_food_json", "SRLegacyFoods"),
}

# FDC nutrient id → INFOODS tagname. Energy: 1008 when present, else Atwater general (2047).
NUTRIENTS = {
    1003: "PROCNT", 1004: "FAT", 1005: "CHOCDF", 2000: "SUGAR",
    1258: "FASAT", 1079: "FIBTG", 1093: "NA",
}
ENERGY = (1008, 2047)


def latest_release(dataset: str) -> str:
    r = httpx.get(LISTING, timeout=60, follow_redirects=True)
    r.raise_for_status()
    found = set(re.findall(rf"FoodData_Central_{DATASETS[dataset][0]}_[\d-]+\.zip", r.text))
    if not found:
        raise RuntimeError(f"fdc: no {dataset} release linked from {LISTING}; the page layout changed")
    return max(found)


def records(payload: dict, key: str):
    for f in filter(None, payload[key]):
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
        yield ingest.Record(
            id=f"fdc:{f['fdcId']}", source="fdc", layer="core", licence="CC0-1.0",
            name=f["description"], lang="en", values=values,
            observed_at=datetime.strptime(published, "%m/%d/%Y" if "/" in published else "%Y-%m-%d").replace(tzinfo=UTC),
        )


def fetch(dataset: str = "foundation", force: bool = False) -> tuple[int, int] | None:
    release = latest_release(dataset)
    fetcher = f"fdc-{dataset}"
    if not force and ingest.already_done(fetcher, release):
        return None
    with tempfile.TemporaryFile() as tmp:  # the zip goes to disk, not memory
        with httpx.stream("GET", BASE + release, timeout=httpx.Timeout(60, read=600), follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                tmp.write(chunk)
        with zipfile.ZipFile(tmp) as z, z.open(next(n for n in z.namelist() if n.endswith(".json"))) as f:
            # ponytail: Foundation and SR Legacy are small; Branded Foods (GBs) needs a streaming
            # JSON parser (ijson) or FDC's CSV files.
            payload = json.load(f)
    return ingest.run(fetcher, release, records(payload, DATASETS[dataset][1]))
