"""Matvaretabellen, the Norwegian food composition table (Mattilsynet), under NLOD 2.0: about 2,100
generic foods, values per 100 g, updated each autumn. Its API serves the whole table as one JSON file."""

import tempfile
from datetime import UTC, datetime

from fooddb import ingest
from fooddb.fetchers import download, json_items

URL = "https://www.matvaretabellen.no/api/en/foods.json"
FETCHER = "matvaretabellen"
LICENCE = "NLOD-2.0"
ATTRIBUTION = ("Contains data from Matvaretabellen (https://www.matvaretabellen.no), Norwegian Food Safety "
               "Authority, made available under the Norwegian Licence for Open Government Data (NLOD) 2.0.")

# Matvaretabellen nutrientId → (INFOODS tagname, unit). "Karbo" is available carbohydrate: Atwater
# with fibre at 2 kcal/g matches its stated energy. "Mono+Di" is total sugars; "Sukker" is added sugar.
# "Alko" is alcohol in g (its euroFirId is ALC).
NUTRIENTS = {
    "Protein": ("PROCNT", "g"), "Fett": ("FAT", "g"), "Mettet": ("FASAT", "g"), "Karbo": ("CHOAVL", "g"),
    "Mono+Di": ("SUGAR", "g"), "Fiber": ("FIBTG", "g"), "Na": ("NA", "mg"), "Alko": ("ALC", "g"),
}
ENERGY = {"energy": ("ENERC_KJ", "kJ"), "calories": ("ENERC_KCAL", "kcal")}


def _groups(group: str | None) -> list[str]:
    """A food group and its parents, narrowest first: "1.4.4" → 1.4.4, 1.4, 1."""
    parts = (group or "").split(".")
    return [f"matvaretabellen:{'.'.join(parts[:n])}" for n in range(len(parts), 0, -1) if group]


def records(foods, observed_at: datetime):
    for f in foods:
        values = {tag: float(q["quantity"]) for key, (tag, unit) in ENERGY.items()
                  if (q := f.get(key) or {}).get("quantity") is not None and q.get("unit") == unit}
        values |= {NUTRIENTS[c["nutrientId"]][0]: float(c["quantity"]) for c in f.get("constituents") or []
                   if c.get("nutrientId") in NUTRIENTS and c.get("quantity") is not None
                   and c.get("unit") == NUTRIENTS[c["nutrientId"]][1]}
        name = (f.get("foodName") or "").strip()
        if not f.get("foodId") or not name or not values:
            continue
        yield ingest.Record(
            id=f"matvaretabellen:{f['foodId']}", source="matvaretabellen", layer="core", licence=LICENCE,
            name=name, lang="en", values=values, observed_at=observed_at, categories=_groups(f.get("foodGroupId")),
        )


def fetch(force: bool = False) -> tuple[int, int] | None:
    """The API is not versioned: the file's SHA-256 is the ref, so an unchanged table loads once.
    Its values carry the day fooddb first saw them."""
    with tempfile.TemporaryFile() as tmp:
        ref = download(URL, tmp)
        if not force and ingest.already_done(FETCHER, ref):
            return None
        return ingest.run(FETCHER, ref, records(json_items(tmp, "foods"), datetime.now(UTC)))
