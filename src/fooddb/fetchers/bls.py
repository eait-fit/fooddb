"""BLS, the German food composition table (Max Rubner-Institut), under CC BY 4.0: about 7,100 foods,
values per 100 g of edible part. The download page links one zip, which holds the data workbook, a
component list and the documentation."""

import html
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime

import httpx

from fooddb import ingest
from fooddb.fetchers import download
from fooddb.fetchers.xlsx import rows

PAGE = "https://www.blsdb.de/download"
UPLOADS = "https://www.blsdb.de/assets/uploads/"
FETCHER = "bls"
LICENCE = "CC-BY-4.0"
ATTRIBUTION = "Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 — Deutsche Nährstoffdatenbank."
ZIP = re.compile(r"/assets/uploads/(BLS_\w+_DE\.zip)")
DATA = re.compile(r"_Daten_\w+\.xlsx$")
VALUE = re.compile(r"^(\S+) .*\[(.+)/100g\]$")

# BLS component code → (INFOODS tagname, unit as the column header states it). CHO is available
# carbohydrate: the documentation (section 5.3) sums sugars, starch, available oligosaccharides and
# polyols, so fibre is not in it: CHOAVL. BLS has no carbohydrate by difference, so no CHOCDF. Energy
# is always calculated (section 5.2) from CHO at 4 kcal/g and fibre at 2 kcal/g. PROT625 is nitrogen
# times 6.25. FIBT is total dietary fibre, SUGAR the sum of mono- and disaccharides, FASAT the sum of
# the saturated fatty acids C4:0 to C24:0. NA is mg, as stored, so nothing is converted.
PARAMETERS = {
    "ENERCJ": ("ENERC_KJ", "kJ"), "ENERCC": ("ENERC_KCAL", "kcal"), "PROT625": ("PROCNT", "g"),
    "CHO": ("CHOAVL", "g"), "FIBT": ("FIBTG", "g"), "FAT": ("FAT", "g"), "SUGAR": ("SUGAR", "g"),
    "FASAT": ("FASAT", "g"), "NA": ("NA", "mg"), "ALC": ("ALC", "g"),
}


def _number(cell: str | None) -> float | None:
    """A cell as a number. TR (traces) is 0, as in the other tables. "-" (no value, which the documentation says
    is not zero), "<LOD", "<LOQ" and a blank cell give no value."""
    if cell == "TR":
        return 0.0
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def records(xlsx, observed_at: datetime):
    """The first row holds the headers: `CODE name [unit/100g]` for a value, with `CODE Datenherkunft` and
    `CODE Referenz` beside it. The food name is the English one, as in the other tables."""
    it = rows(xlsx)
    header = next(it)
    at = {m[1]: (i, m[2]) for i, h in enumerate(header) if h and (m := VALUE.match(h))}
    for code, (_, unit) in PARAMETERS.items():
        if code not in at or at[code][1] != unit:
            raise RuntimeError(f"bls: component {code} is not in {unit}; the file layout changed")
    if missing := [c for c in ("BLS Code", "Food name") if c not in header]:
        raise RuntimeError(f"bls: columns {missing} missing; the file layout changed")
    code_at, name_at = header.index("BLS Code"), header.index("Food name")
    de_at = header.index("Lebensmittelbezeichnung") if "Lebensmittelbezeichnung" in header else None
    for row in it:
        def cell(i: int) -> str | None:
            return row[i] if i < len(row) else None

        values = {tag: v for code, (tag, _) in PARAMETERS.items() if (v := _number(cell(at[code][0]))) is not None}
        code, name = (cell(code_at) or "").strip(), (cell(name_at) or "").strip()
        if not code or not name or not values:
            continue
        yield ingest.Record(
            id=f"bls:{code}", source="bls", layer="core", licence=LICENCE, name=name, lang="en",
            values=values, observed_at=observed_at, categories=[f"bls:{code[0]}"],
            names={"de": de} if de_at is not None and (de := (cell(de_at) or "").strip()) else {},
        )


def link(page: str) -> str:
    """The zip that the download page offers, as an address that needs no token."""
    m = ZIP.search(html.unescape(page))
    if m is None:
        raise RuntimeError(f"bls: no zip on {PAGE}; the page layout changed")
    return UPLOADS + m[1]


def dataset(z: zipfile.ZipFile) -> zipfile.ZipInfo:
    """The data workbook in the zip."""
    f = next((i for i in z.infolist() if DATA.search(i.filename)), None)
    if f is None:
        raise RuntimeError(f"bls: no data workbook in {z.namelist()}; the zip layout changed")
    return f


def fetch(force: bool = False) -> tuple[int, int] | None:
    """The zip is named for the release, and the server states its size and change date, so a HEAD request
    gives the ref and an unchanged file is not downloaded. The values carry the day the workbook was saved."""
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url = link(r.text)
    h = httpx.head(url, timeout=60, follow_redirects=True)
    h.raise_for_status()
    if not (modified := h.headers.get("last-modified")) or not (size := h.headers.get("content-length")):
        raise RuntimeError(f"bls: {url} states no size or change date; the server changed")
    ref = f"{url.rsplit('/', 1)[1]} {size} {modified}"
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as tmp, tempfile.TemporaryFile() as workbook:
        download(url, tmp)
        with zipfile.ZipFile(tmp) as z:
            member = dataset(z)
            with z.open(member) as src:
                shutil.copyfileobj(src, workbook)
        workbook.seek(0)
        observed_at = datetime(*member.date_time, tzinfo=UTC)
        return ingest.run(FETCHER, ref, records(workbook, observed_at))
