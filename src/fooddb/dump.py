"""Monthly ODbL dump: the Open Food Facts-derived layer of the newest final snapshot day, as gzipped NDJSON
next to a JSON manifest. ODbL share-alike applies to it, so its routes need no key; they only count
against the rate limit."""

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic_core import to_json
from sqlalchemy import text

from fooddb import export, resolve, snapshot
from fooddb.db import engine
from fooddb.fetchers.off import LICENCE

PREFIX = "fooddb-off-odbl-"
ATTRIBUTION = ("Contains information from Open Food Facts (https://world.openfoodfacts.org), which is made "
               "available here under the Open Database License (ODbL) 1.0.")
LICENCE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
TERMS_URL = "https://github.com/eait-fit/fooddb/blob/main/docs/data-licence.md"


def directory() -> Path:
    return Path(os.environ.get("FOODDB__BACKEND__DUMP_DIR", "dumps"))


def odbl(p: dict) -> dict | None:
    """The ODbL part of one exported product: its OFF records, and each field and value tagged ODbL.
    None when the product has no OFF record."""
    records = [r for r in p["records"] if r.startswith("off:")]
    if not records:
        return None

    def ours(tag: dict | None) -> dict | None:
        return tag if tag and tag["licence"] == LICENCE else None

    return {"id": p["id"], "snapshot": p["snapshot"], "records": records,
            **{f: ours(p[f]) for f in (*resolve.FIELDS, "flags")},
            "gtin14": [g for g in p["gtin14"] if ours(g)],
            "per_100": {n: v for n, v in p["per_100"].items() if ours(v)}}


def final_day() -> date | None:
    with engine().connect() as conn:
        return conn.execute(text("select max(day) from snapshot where day < :t"), {"t": snapshot.today()}).scalar_one()


def write(out: Path | None = None) -> dict | None:
    """Dump the newest final day into `out`, then keep only the newest FOODDB__BACKEND__DUMP_KEEP dumps there.
    Returns the manifest, or None while no day is final."""
    day = final_day()
    if day is None:
        return None
    out = out or directory()
    out.mkdir(parents=True, exist_ok=True)
    name = f"{PREFIX}{day.isoformat()}.ndjson.gz"
    sha, size, count = hashlib.sha256(), 0, 0

    def lines():
        nonlocal count
        for p in filter(None, map(odbl, export.products(day, "off"))):
            count += 1
            yield to_json(p) + b"\n"

    part = out / f"{name}.part"
    with part.open("wb") as f:
        for chunk in export.gzipped(lines()):
            f.write(chunk)
            sha.update(chunk)
            size += len(chunk)
    part.replace(out / name)
    manifest = {"name": name, "day": day.isoformat(), "products": count, "size": size, "sha256": sha.hexdigest(),
                "licence": LICENCE, "licence_url": LICENCE_URL, "attribution": ATTRIBUTION, "terms": TERMS_URL,
                "generated_at": datetime.now(UTC).isoformat()}
    part = out / f"{PREFIX}{day.isoformat()}.json.part"
    part.write_text(json.dumps(manifest, indent=2))
    part.replace(out / f"{PREFIX}{day.isoformat()}.json")
    for old in manifests(out)[int(os.environ.get("FOODDB__BACKEND__DUMP_KEEP", "3")):]:
        (out / f"{PREFIX}{old['day']}.json").unlink()
        (out / old["name"]).unlink(missing_ok=True)
    return manifest


def manifests(where: Path | None = None) -> list[dict]:
    """The manifests in the dump directory, newest day first."""
    return [json.loads(p.read_text()) for p in sorted((where or directory()).glob(f"{PREFIX}*.json"), reverse=True)]


router = APIRouter(prefix="/v1/dumps", tags=["dumps"])


@router.get("")
def list_dumps() -> dict:
    """The monthly ODbL dumps of the Open Food Facts layer, newest first: name, day, size, sha256, licence."""
    return {"items": manifests()}


@router.get("/{name}")
def download(name: str, if_none_match: str = Header("")) -> Response:
    """One dump file, gzipped NDJSON, one product per line. The ETag is its sha256."""
    path = directory() / name
    m = next((m for m in manifests() if m["name"] == name), None)
    if m is None or not path.is_file():
        raise HTTPException(404, f"no dump named {name}")
    etag = f'"{m["sha256"]}"'
    if "*" in if_none_match or etag in {t.strip().removeprefix("W/") for t in if_none_match.split(",")}:
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(path, media_type="application/gzip", filename=name, headers={"ETag": etag})
