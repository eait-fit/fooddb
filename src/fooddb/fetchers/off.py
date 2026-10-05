"""Open Food Facts daily delta files (ODbL). Stored in the "off" layer, never mixed into core."""

import gzip
import json
import zlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from datetime import UTC, datetime

import httpx
from loguru import logger

from fooddb import gtin, ingest

DELTA = "https://static.openfoodfacts.org/data/delta/"
DUMP = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"  # ~13 GB gzipped
FETCHER = "off-delta"
DUMP_FETCHER = "off-dump"
LICENCE = "ODbL-1.0"

# OFF nutrient key → INFOODS tagname. Values are converted to our units (g, kcal; sodium in mg).
NUTRIENTS = {
    "energy-kcal": "ENERC_KCAL", "proteins": "PROCNT", "fat": "FAT", "carbohydrates": "CHOCDF",
    "sugars": "SUGAR", "saturated-fat": "FASAT", "fiber": "FIBTG", "sodium": "NA",
}
TO_GRAMS = {"g": 1, "mg": 1e-3, "µg": 1e-6, "mcg": 1e-6}
KJ_PER_KCAL = 4.184


def delta_files() -> list[str]:
    """All published delta files, oldest first (names carry from/to unix timestamps)."""
    r = httpx.get(DELTA + "index.txt", timeout=60)
    r.raise_for_status()
    index = r.text.split()
    return sorted(index, key=lambda n: int(n.rsplit("_", 1)[1].split(".")[0]))


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # drop NaN


def per_100(p: dict) -> dict[str, float]:
    """Per-100 g/ml values. OFF's current schema has nutrition.aggregated_set; older dumps have
    flat nutriments.<key>_100g (grams, kcal)."""
    out: dict[str, float] = {}
    agg = (p.get("nutrition") or {}).get("aggregated_set") or {}
    if agg.get("per") in ("100g", "100ml"):
        for key, tag in NUTRIENTS.items():
            n = agg.get("nutrients", {}).get(key) or {}
            v, unit = _num(n.get("value")), n.get("unit")
            if v is None:
                continue
            if tag == "ENERC_KCAL":
                if unit == "kcal":
                    out[tag] = v
            elif unit in TO_GRAMS:
                out[tag] = v * TO_GRAMS[unit] * (1000 if tag == "NA" else 1)
        kj = agg.get("nutrients", {}).get("energy-kj") or {}
        if "ENERC_KCAL" not in out and (v := _num(kj.get("value"))) is not None and kj.get("unit") == "kJ":
            out["ENERC_KCAL"] = v / KJ_PER_KCAL  # many EU labels state kJ only
        return out
    flat = p.get("nutriments") or {}
    for key, tag in NUTRIENTS.items():
        v = _num(flat.get(f"{key}_100g"))
        if v is not None:
            out[tag] = v * (1000 if tag == "NA" else 1)
    if "ENERC_KCAL" not in out and (v := _num(flat.get("energy-kj_100g"))) is not None:
        out["ENERC_KCAL"] = v / KJ_PER_KCAL
    return out


def basis(p: dict) -> str:
    """Whether the values are per 100 g or per 100 ml (drinks)."""
    agg = (p.get("nutrition") or {}).get("aggregated_set") or {}
    per = agg.get("per") or p.get("nutrition_data_per")
    return "100ml" if per == "100ml" else "100g"


def records(lines: Iterable[bytes]):
    bad = 0
    for line in lines:
        try:
            p = json.loads(line)
        except ValueError:
            bad += 1  # one corrupt line must not sink a 4M-product file
            continue
        code = gtin.normalize(p.get("code"))
        name = (p.get("product_name") or "").strip()
        values = per_100(p)
        if not code or not name or not values:
            continue
        yield ingest.Record(
            id=f"off:{code}", source="off", layer="off", licence=LICENCE, gtin14=code, name=name,
            brand=(p.get("brands") or None), lang=p.get("lang"), values=values, basis=basis(p),
            serving_text=p.get("serving_size"), serving_g=_num(p.get("serving_quantity")),
            observed_at=datetime.fromtimestamp(int(p.get("last_modified_t") or 0), UTC),
        )
    if bad:
        logger.warning(f"off: skipped {bad} lines that are not valid JSON")


def file_lines(path: Path) -> Iterator[bytes]:
    with gzip.open(path, "rb") as f:
        yield from f


def url_lines(url: str) -> Iterator[bytes]:
    """Decompress a .gz download as it arrives, one line at a time: nothing lands on disk and
    memory stays flat however large the file is."""
    inflate = zlib.decompressobj(wbits=31)
    rest = b""
    with httpx.stream("GET", url, timeout=httpx.Timeout(60, read=300), follow_redirects=True) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            *lines, rest = (rest + inflate.decompress(chunk)).split(b"\n")
            yield from lines
    rest += inflate.flush()
    if rest.strip():
        yield rest


def load(source: Path | Iterable[bytes], fetcher: str, ref: str) -> tuple[int, int]:
    """Ingest one OFF JSONL source: a .gz file path, or lines already being streamed."""
    lines = file_lines(source) if isinstance(source, Path) else source
    return ingest.run(fetcher, ref, records(lines))


def todo(index: list[str], done: set[str], first_run: int) -> list[str]:
    """Delta files to ingest, oldest first: every file not done since the earliest done one, so a
    stopped worker or a failed day is caught up. With nothing done yet, the newest `first_run`.
    If every done file has rotated out of the index (OFF keeps about two weeks), the whole index
    is taken; changes older than that need a full-dump reload."""
    if not done:
        return index[-first_run:]
    seen = [i for i, f in enumerate(index) if f in done]
    start = seen[0] if seen else 0
    return [f for f in index[start:] if f not in done]


def fetch(max_files: int = 1) -> list[tuple[str, int, int]]:
    """Ingest every pending delta (see `todo`); `max_files` sizes the first run only."""
    index = delta_files()
    done = ingest.done_refs(FETCHER)
    if done and not any(f in done for f in index):
        logger.warning("off: every ingested delta has rotated out of the index; a full-dump reload is needed")
    out = []
    for name in todo(index, done, max_files):
        foods, obs = load(url_lines(DELTA + name), FETCHER, name)
        out.append((name, foods, obs))
    if not out:
        logger.info(f"off: no new deltas (newest in index: {index[-1] if index else 'none'})")
    return out


def fetch_dump(force: bool = False) -> tuple[int, int] | None:
    """The full OFF dump, streamed (hours for ~4M products). The ref is the dump's Last-Modified,
    so a dump is loaded once; the daily deltas keep it current afterwards."""
    head = httpx.head(DUMP, timeout=60, follow_redirects=True)
    head.raise_for_status()
    ref = head.headers.get("last-modified") or "unknown"
    if not force and ingest.already_done(DUMP_FETCHER, ref):
        return None
    return load(url_lines(DUMP), DUMP_FETCHER, ref)
