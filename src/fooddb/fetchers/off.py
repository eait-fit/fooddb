"""Open Food Facts daily delta files (ODbL). Stored in the "off" layer, never mixed into core."""

import gzip
import json
import re
import time
import zlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from datetime import UTC, datetime

import httpx
from loguru import logger
from sqlalchemy import select, update

from fooddb import gtin, ingest
from fooddb.db import engine, food, observation

DELTA = "https://static.openfoodfacts.org/data/delta/"
DUMP = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"  # ~13 GB gzipped
FETCHER = "off-delta"
DUMP_FETCHER = "off-dump"
LICENCE = "ODbL-1.0"
IMAGES = "https://images.openfoodfacts.org/images/products/"
IMAGE_KINDS = ("front", "nutrition")
API = "https://world.openfoodfacts.org/api/v2/product/"
USER_AGENT = "fooddb-images/0.1 (https://github.com/eait-fit/fooddb)"  # OFF asks for AppName/Version (contact)
# OFF allows 15 product reads a minute per IP (API introduction, "Rate limits"). 8 s is 7.5 a minute.
# ponytail: one worker, fixed pause; adapt to the Retry-After header if OFF ever tightens the limit.
PAUSE_S = 8.0

# OFF nutrient key → INFOODS tagname. Values are converted to our units (g, kcal, kJ; sodium in mg).
# "carbohydrates" is what the label calls carbohydrate; its code depends on the market (`carbs_code`).
NUTRIENTS = {
    "energy-kcal": "ENERC_KCAL", "energy-kj": "ENERC_KJ", "proteins": "PROCNT", "fat": "FAT",
    "carbohydrates": "CHO", "carbohydrates-total": "CHOCDF",
    "sugars": "SUGAR", "saturated-fat": "FASAT", "fiber": "FIBTG", "sodium": "NA",
}
ENERGY_UNITS = {"ENERC_KCAL": "kcal", "ENERC_KJ": "kJ"}
TO_GRAMS = {"g": 1, "mg": 1e-3, "µg": 1e-6, "mcg": 1e-6}
KJ_PER_KCAL = 4.184

# Label carbohydrate includes fibre (by difference) in the US and Canada. It excludes fibre
# (available carbohydrate) under EU 1169/2011, in the UK, the EFTA states, Australia and New Zealand.
TOTAL_CARB_MARKETS = {"en:united-states", "en:canada"}
AVAILABLE_CARB_MARKETS = {f"en:{c}" for c in (
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech-republic", "denmark", "estonia", "finland",
    "france", "germany", "greece", "hungary", "ireland", "italy", "latvia", "lithuania", "luxembourg", "malta",
    "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia", "spain", "sweden",
    "united-kingdom", "switzerland", "norway", "iceland", "liechtenstein", "australia", "new-zealand",
)}
CARBS_UNKNOWN = "carbs-regime-unknown"


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


def carbs_code(p: dict) -> str | None:
    """CHOCDF or CHOAVL for OFF's `carbohydrates`, from the markets the product is sold in. None when
    they do not say, or say both."""
    markets = set(p.get("countries_tags") or [])
    total, available = bool(markets & TOTAL_CARB_MARKETS), bool(markets & AVAILABLE_CARB_MARKETS)
    return None if total == available else "CHOCDF" if total else "CHOAVL"


def _parsed(p: dict) -> dict[str, float]:
    """Per-100 g/ml values, with label carbohydrate still under "CHO". OFF's current schema has
    nutrition.aggregated_set; older dumps have flat nutriments.<key>_100g (grams, kcal, kJ)."""
    out: dict[str, float] = {}
    agg = (p.get("nutrition") or {}).get("aggregated_set") or {}
    if agg.get("per") in ("100g", "100ml"):
        for key, tag in NUTRIENTS.items():
            n = agg.get("nutrients", {}).get(key) or {}
            v, unit = _num(n.get("value")), n.get("unit")
            if v is None:
                continue
            if tag in ENERGY_UNITS:
                if unit == ENERGY_UNITS[tag]:
                    out[tag] = v
            elif unit in TO_GRAMS:
                out[tag] = v * TO_GRAMS[unit] * (1000 if tag == "NA" else 1)
    else:
        flat = p.get("nutriments") or {}
        for key, tag in NUTRIENTS.items():
            v = _num(flat.get(f"{key}_100g"))
            if v is not None:
                out[tag] = v * (1000 if tag == "NA" else 1)
    if "ENERC_KCAL" not in out and "ENERC_KJ" in out:
        out["ENERC_KCAL"] = out["ENERC_KJ"] / KJ_PER_KCAL  # many EU labels state kJ only
    return out


def coded(p: dict) -> tuple[dict[str, float], list[str]]:
    """Per-100 g/ml values under their INFOODS codes, and the flags for what was guessed. Label
    carbohydrate goes under the code of its market (`carbs_code`), else CHOCDF with CARBS_UNKNOWN.
    An explicit total carbohydrate is CHOCDF."""
    out, flags = _parsed(p), []
    if (v := out.pop("CHO", None)) is not None:
        if (code := carbs_code(p)) is None:
            code, flags = "CHOCDF", [CARBS_UNKNOWN]
        out.setdefault(code, v)
    return out, flags


def per_100(p: dict) -> dict[str, float]:
    return coded(p)[0]


def basis(p: dict) -> str:
    """Whether the values are per 100 g or per 100 ml (drinks)."""
    agg = (p.get("nutrition") or {}).get("aggregated_set") or {}
    per = agg.get("per") or p.get("nutrition_data_per")
    return "100ml" if per == "100ml" else "100g"


def _revs(images: dict, kind: str) -> dict[str, int]:
    """lang → rev of a kind's selected image, from the new shape (`selected.<kind>.<lang>`) or the old one (`<kind>_<lang>`)."""
    new = (images.get("selected") or {}).get(kind)
    by_lang = new if isinstance(new, dict) and new else {k[len(kind) + 1:]: v for k, v in images.items() if k.startswith(kind + "_")}
    return {lang: int(v["rev"]) for lang, v in by_lang.items()
            if re.fullmatch(r"[A-Za-z0-9_-]{1,12}", lang) and isinstance(v, dict) and str(v.get("rev")).isdigit()}


def image_refs(p: dict) -> dict[str, dict]:
    """{kind: {"lang", "rev"}} for the front and nutrition photos of an OFF product: the product's main language
    if it has one, else the first language by name. Only the reference, never the image."""
    images, out = p.get("images"), {}
    for kind in IMAGE_KINDS if isinstance(images, dict) else ():
        revs = _revs(images, kind)
        if lang := (str(p.get("lang")) if str(p.get("lang")) in revs else min(revs, default=None)):
            out[kind] = {"lang": lang, "rev": revs[lang]}
    return out


def code13(code: str) -> str:
    """An OFF code from a GTIN-14: leading zeros removed, then padded to 13 digits."""
    return code.lstrip("0").rjust(13, "0")


def image_url(code: str, kind: str, lang: str, rev: int, size: int = 400) -> str:
    """OFF's address of a selected image. The folder is the barcode padded to 13 digits and split 3/3/3/rest
    (openfoodfacts.github.io/openfoodfacts-server/api/how-to-download-images)."""
    folder = re.sub(r"^(...)(...)(...)(.*)$", r"\1/\2/\3/\4", code13(code))
    return f"{IMAGES}{folder}/{kind}_{lang}.{rev}.{size}.jpg"


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
        values, guessed = coded(p)
        if not code or not name or not values:
            continue
        yield ingest.Record(
            id=f"off:{code}", source="off", layer="off", licence=LICENCE, gtin14=code, name=name,
            brand=(p.get("brands") or None), lang=p.get("lang"), images=image_refs(p), values=values, basis=basis(p),
            extra_flags=guessed, categories=p.get("categories_tags") or [], labels=p.get("labels_tags") or [],
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


def backfill_images(limit: int | None = None, pause: float = PAUSE_S, transport: httpx.BaseTransport | None = None) -> tuple[int, int]:
    """Photo references for the OFF records that have pending values and none stored (`food.images` null), read one
    product at a time from OFF's API. A product OFF does not know, or without a front or nutrition photo, gets `{}`, so
    the next run skips it. Stops on a rate limit, an outage or a network error: the rest waits for the next run.
    Returns (records checked, records with a photo)."""
    pending = select(observation.c.food_id).where(observation.c.status == "pending", observation.c.food_id == food.c.id)
    with engine().connect() as conn:
        ids = list(conn.execute(
            select(food.c.id).where(food.c.source == "off", food.c.images.is_(None), pending.exists())
            .order_by(food.c.id).limit(limit)).scalars())
    checked = found = 0
    with httpx.Client(transport=transport, headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for i, fid in enumerate(ids):
            if i:
                time.sleep(pause)
            r = client.get(f"{API}{code13(fid.removeprefix('off:'))}.json", params={"fields": "images,lang"})
            if r.status_code in (429, 503):
                raise RuntimeError(f"off: HTTP {r.status_code} after {checked} products: rate-limited or down, run again later")
            if r.status_code not in (200, 404):
                logger.warning(f"off: {fid}: HTTP {r.status_code}, skipped")
                continue
            refs = image_refs(r.json().get("product") or {}) if r.status_code == 200 else {}
            with engine().begin() as conn:
                conn.execute(update(food).where(food.c.id == fid, food.c.images.is_(None)).values(images=refs))
            checked, found = checked + 1, found + bool(refs)
    logger.info(f"off images: {checked} products checked, {found} with a photo")
    return checked, found
