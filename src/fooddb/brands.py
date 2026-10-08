"""A brand upload becomes the observations of one source record, `brand:<gtin14>`, through the shared
write path, with the label photo as evidence. The checks run as for every source. Every value waits
for review unless the GS1 verifier says the brand owns the barcode."""

import math
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import text

from fooddb import gs1, gtin, ingest
from fooddb.db import engine
from fooddb.labels import NUTRIENTS, LabelRead, photos

FETCHER = "brand"
LICENCE = "LicenseRef-fooddb"  # fooddb's own terms for its core data
UNVERIFIED = "brand-unverified"
MISMATCH = "brand-gs1-mismatch"
LABELS = {
    "ENERC_KCAL": "Energy (kcal)", "ENERC_KJ": "Energy (kJ)", "PROCNT": "Protein (g)", "FAT": "Fat (g)",
    "CHOCDF": "Carbohydrate, total (g)", "CHOAVL": "Carbohydrate, available (g)", "SUGAR": "Sugars (g)",
    "FASAT": "Saturated fat (g)", "FIBTG": "Fibre (g)", "NA": "Sodium (mg)"}
TEXT_FIELDS = ("barcode", "name", "brand", "basis", "serving_text", "serving_g", *NUTRIENTS)


class Refused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def parse(form: Mapping[str, str]) -> tuple[str, LabelRead]:
    """The GTIN-14 and the validated values of an upload's text fields. Blank fields are absent."""
    f = {k: v.strip() for k in TEXT_FIELDS if isinstance(v := form.get(k), str) and v.strip()}
    if (code := gtin.normalize(f.get("barcode"))) is None:
        raise Refused("barcode: not a valid global GTIN")
    for field in ("name", "brand"):
        if field not in f:
            raise Refused(f"{field}: required")
    try:
        values = {k: float(f[k]) for k in NUTRIENTS if k in f}
        serving_g = float(f["serving_g"]) if "serving_g" in f else None
    except ValueError as e:
        raise Refused(f"a number is not a number: {e}")
    if not values:
        raise Refused("at least one value is required")
    if any(not math.isfinite(v) or v < 0 for v in values.values()):
        raise Refused("values: must be finite and not negative")
    try:
        read = LabelRead(values=values, basis=f.get("basis", "100g"), serving_text=f.get("serving_text"),
                         serving_g=serving_g, name=f["name"], brand=f["brand"], barcode=code, confidence=1.0)
    except ValidationError as e:
        raise Refused("; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
    return code, read


def _known(record_id: str) -> dict | None:
    """The metadata of a record that already serves an accepted value."""
    with engine().connect() as conn:
        row = conn.execute(text("""
            select name, brand, lang, serving_text, serving_g from food
            where id = :id and exists (select 1 from observation where food_id = food.id and status = 'accepted')
        """), {"id": record_id}).mappings().first()
    return dict(row) if row else None


def record(code: str, read: LabelRead, sha: str, verdict: gs1.Verdict) -> ingest.Record:
    flags = [] if verdict == "verified" else [UNVERIFIED] + [MISMATCH] * (verdict == "not_verified")
    r = ingest.Record(
        id=f"{FETCHER}:{code}", source=FETCHER, layer="core", licence=LICENCE, name=read.name or "",
        observed_at=datetime.now(UTC), values=read.values, basis=read.basis, brand=read.brand, gtin14=code,
        serving_text=read.serving_text, serving_g=read.serving_g, extra_flags=flags, evidence=sha,
        review_all=bool(flags))
    if flags and (served := _known(r.id)):  # an unverified upload must not rewrite what is already served
        for k, v in served.items():
            setattr(r, k, v)
    return r


def submit(form: Mapping[str, str], photo: bytes) -> dict:
    """Validate, store the photo, check the brand with GS1, ingest. Raises Refused."""
    from fooddb import jobs

    code, read = parse(form)
    if not photo:
        raise Refused("photo: a label photo is required")
    try:
        sha, _ = photos.store(photo)
    except photos.Refused as e:
        raise Refused(str(e), e.status)
    verdict = gs1.check(code, read.brand or "")
    r = record(code, read, sha, verdict)
    ingest.run(FETCHER, sha, [r])
    jobs._rematch(FETCHER)
    return {"record": r.id, "photo": sha, "verification": verdict,
            "review": "checks only" if verdict == "verified" else "required"}
