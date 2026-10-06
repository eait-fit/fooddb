"""Frida, the Danish food composition database (DTU National Food Institute), under CC BY 4.0: about
1,400 generic foods, values per 100 g. DTU Data publishes each version as an Excel workbook, and the
record at a fixed address always lists the newest one."""

import tempfile
from datetime import datetime

import httpx

from fooddb import ingest
from fooddb.fetchers import download
from fooddb.fetchers.xlsx import rows

ARTICLE = "https://api.figshare.com/v2/articles/29500682"
FETCHER = "frida"
LICENCE = "CC-BY-4.0"
ATTRIBUTION = ("Frida Food Data (https://frida.fooddata.dk), National Food Institute, Technical University "
               "of Denmark. CC BY 4.0.")
ROOT = "1"  # the group that holds every top-level group

# Frida ParameterID → (its English name, INFOODS tagname). Units as the Data_Table states them: energy kJ and
# kcal, sodium mg, the rest g per 100 g. The documentation (section 5.2) defines 170 as dry matter minus
# protein, fat, ash, organic acids and the residual, so fibre is in it: CHOCDF. It defines 172 as 170 minus
# dietary fibre: CHOAVL. Energy uses 172 at 4 kcal/g and fibre at 2 kcal/g (EU 1169/2011). 245 is the sum of
# mono- and disaccharides, and 168 is the sum of the soluble and insoluble fibre fractions.
PARAMETERS = {
    137: ("Energy (kJ)", "ENERC_KJ"), 356: ("Energy (kcal)", "ENERC_KCAL"), 218: ("Protein", "PROCNT"),
    170: ("Carbohydrate by difference", "CHOCDF"), 172: ("Available carbohydrates", "CHOAVL"),
    168: ("Dietary fibre", "FIBTG"), 141: ("Fat", "FAT"), 245: ("Sum sugars", "SUGAR"),
    248: ("Sum saturated fatty acids", "FASAT"), 201: ("Sodium", "NA"),
}


def _number(cell: str | None) -> float | None:
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def records(xlsx, observed_at: datetime):
    """Data_Table has four header rows: the parameter names in Danish and in English, their units and
    their ParameterIDs. Each food row ends with its group. A blank cell is a value that Frida does not state."""
    parent = {r[3]: r[0] for r in list(rows(xlsx, "FoodGroup"))[1:] if len(r) > 3}
    it = rows(xlsx, "Data_Table")
    _, english, _, ids = (next(it) for _ in range(4))
    at = {v: i for i, v in enumerate(ids) if v}
    for pid, (name, _) in PARAMETERS.items():
        i = at.get(str(pid))
        if i is None or " ".join(((english[i] if i < len(english) else None) or "").split()) != name:
            raise RuntimeError(f"frida: parameter {pid} is not {name!r}; the file layout changed")
    if missing := [c for c in ("↓FoodName", "↓FoodID/→ParameterID", "FoodGroupID") if c not in at]:
        raise RuntimeError(f"frida: columns {missing} missing; the file layout changed")
    for row in it:
        def cell(i: int) -> str | None:
            return row[i] if i < len(row) else None

        values = {tag: v for pid, (_, tag) in PARAMETERS.items() if (v := _number(cell(at[str(pid)]))) is not None}
        code, name, group = cell(at["↓FoodID/→ParameterID"]), (cell(at["↓FoodName"]) or "").strip(), cell(at["FoodGroupID"])
        if not code or not name or not values:
            continue
        yield ingest.Record(
            id=f"frida:{code}", source="frida", layer="core", licence=LICENCE, name=name, lang="en",
            values=values, observed_at=observed_at,
            categories=[f"frida:{g}" for g in dict.fromkeys((group, parent.get(group))) if g and g != ROOT],
        )


def newest(article: dict) -> tuple[str, str, datetime]:
    """The newest version's workbook: its download address, its ref and the day DTU Data published it."""
    f = next((f for f in article["files"] if f["name"].endswith("Dataset.xlsx")), None)
    if f is None:
        raise RuntimeError(f"frida: no dataset workbook in {ARTICLE}; the record layout changed")
    return f["download_url"], f"{f['name']} {f['computed_md5']}", datetime.fromisoformat(article["published_date"])


def fetch(force: bool = False) -> tuple[int, int] | None:
    r = httpx.get(ARTICLE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url, ref, observed_at = newest(r.json())
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as tmp:
        download(url, tmp)
        return ingest.run(FETCHER, ref, records(tmp, observed_at))
