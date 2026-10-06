"""A label read becomes the observations of one source record, `label:<photo sha256>`, through the
shared write path. The checks run as for every source. A read is served without review only when the
server read it with a confidence at or above the floor."""

import os
from datetime import UTC, datetime

from fooddb import gtin, ingest
from fooddb.labels import LabelRead, photos

FETCHER = "label"
LICENCE = "LicenseRef-fooddb"  # fooddb's own terms for its core data
LOW_CONFIDENCE = "label-low-confidence"
CLIENT_READ = "label-client-read"


def floor() -> float:
    return float(os.environ.get("FOODDB__BACKEND__LABEL_CONFIDENCE_FLOOR", "0.9"))


def record(sha: str, read: LabelRead, hints: dict[str, str], client_read: bool) -> ingest.Record:
    flags = [LOW_CONFIDENCE] * (read.confidence < floor()) + [CLIENT_READ] * client_read
    return ingest.Record(
        id=f"{FETCHER}:{sha}", source=FETCHER, layer="core", licence=LICENCE,
        name=read.name or hints.get("name") or f"Label {sha[:12]}", observed_at=datetime.now(UTC),
        values=read.values, basis=read.basis, brand=read.brand, lang=read.lang,
        gtin14=gtin.normalize(hints.get("barcode")) or gtin.normalize(read.barcode),
        serving_text=read.serving_text, serving_g=read.serving_g,
        extra_flags=flags, evidence=sha, review_all=bool(flags),
    )


def process(sha: str, hints: dict[str, str], read: str | dict | None = None) -> str:
    """Read the stored photo (or take the read the client sent) and ingest it. Returns the record id."""
    from fooddb import labels

    if read is None:
        image = photos.load(sha)
        result = labels.reader().read(image, photos.sniff(image), hints)
    else:
        result = labels.parse(read)
    r = record(sha, result, hints, client_read=read is not None)
    ingest.run(FETCHER, sha, [r])
    return r.id
