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
RELEASE_4_0 = "BLS_4_0_"
ERRATUM_REF = "erratum-2026-08"

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

# The MRI errata of August 2026 (https://www.blsdb.de/assets/uploads/Erratum_BLS_4_0_DE.pdf) hold until BLS 4.1,
# and apply to the 4.0 file only. Section 3: the software added the available oligosaccharides (OLSAC) to
# the energy a second time, at 8 kJ/g and 2 kcal/g (as fibre); CHO already counts them at 17 kJ/g and 4 kcal/g.
# Section 6: the fat of "Sardelle roh" (T104100) is 13.7 g where 2.3 to 6.3 g is usual, with no value yet. Its
# energy and saturated fat depend on it, and so do the entries of appendix 7.7 that are anchovy (the other 10,
# recipes with anchovy as a minor ingredient, keep their values).
OLSAC_KJ, OLSAC_KCAL = 8, 2
ANCHOVY = {"T104100", "T104162", "T104172", "T104182", "T104400", "T104702", "T860100"}
ANCHOVY_WITHHELD = {"FAT", "FASAT", "ENERC_KJ", "ENERC_KCAL"}


def _number(cell: str | None) -> float | None:
    """A cell as a number. TR (traces) is 0, as in the other tables. "-" (no value, which the documentation says
    is not zero), "<LOD", "<LOQ" and a blank cell give no value."""
    if cell == "TR":
        return 0.0
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def records(xlsx, observed_at: datetime, erratum: bool = False):
    """The first row holds the headers: `CODE name [unit/100g]` for a value, with `CODE Datenherkunft` and
    `CODE Referenz` beside it. The food name is the English one, as in the other tables. With `erratum`, the
    values follow the MRI errata of August 2026 (see above)."""
    it = rows(xlsx)
    header = next(it)
    at = {m[1]: (i, m[2]) for i, h in enumerate(header) if h and (m := VALUE.match(h))}
    for code, (_, unit) in PARAMETERS.items():
        if code not in at or at[code][1] != unit:
            raise RuntimeError(f"bls: component {code} is not in {unit}; the file layout changed")
    if erratum and at.get("OLSAC", (0, None))[1] != "g":
        raise RuntimeError("bls: component OLSAC is not in g; the file layout changed")
    if missing := [c for c in ("BLS Code", "Food name") if c not in header]:
        raise RuntimeError(f"bls: columns {missing} missing; the file layout changed")
    code_at, name_at = header.index("BLS Code"), header.index("Food name")
    de_at = header.index("Lebensmittelbezeichnung") if "Lebensmittelbezeichnung" in header else None
    for row in it:
        def cell(i: int) -> str | None:
            return row[i] if i < len(row) else None

        values = {tag: v for code, (tag, _) in PARAMETERS.items() if (v := _number(cell(at[code][0]))) is not None}
        code, name = (cell(code_at) or "").strip(), (cell(name_at) or "").strip()
        if erratum:
            if (olsac := _number(cell(at["OLSAC"][0]))) and olsac > 0:
                for tag, per_g in (("ENERC_KJ", OLSAC_KJ), ("ENERC_KCAL", OLSAC_KCAL)):
                    if tag in values:
                        values[tag] = round(values[tag] - per_g * olsac, 2)
            if code in ANCHOVY:
                values = {k: v for k, v in values.items() if k not in ANCHOVY_WITHHELD}
        if not code or not name or not values:
            continue
        yield ingest.Record(
            id=f"bls:{code}", source="bls", layer="core", licence=LICENCE, name=name, lang="en",
            values=values, observed_at=observed_at, categories=[f"bls:{code[0]}"],
            names={"de": de} if de_at is not None and (de := (cell(de_at) or "").strip()) else {},
        )


def ref(name: str, size: str, modified: str) -> str:
    """The run's ref. A 4.0 zip carries the errata in it, so a zip that was loaded before the errata were
    applied is loaded again once."""
    return f"{name} {size} {modified}" + (f" {ERRATUM_REF}" if name.startswith(RELEASE_4_0) else "")


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
    gives the ref and an unchanged file is not downloaded. The values carry the day the workbook was saved. The
    errata correct the 4.0 file, so the zip name decides."""
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url = link(r.text)
    h = httpx.head(url, timeout=60, follow_redirects=True)
    h.raise_for_status()
    if not (modified := h.headers.get("last-modified")) or not (size := h.headers.get("content-length")):
        raise RuntimeError(f"bls: {url} states no size or change date; the server changed")
    name = url.rsplit("/", 1)[1]
    run_ref = ref(name, size, modified)
    if not force and ingest.already_done(FETCHER, run_ref):
        return None
    with tempfile.TemporaryFile() as tmp, tempfile.TemporaryFile() as workbook:
        download(url, tmp)
        with zipfile.ZipFile(tmp) as z:
            member = dataset(z)
            with z.open(member) as src:
                shutil.copyfileobj(src, workbook)
        workbook.seek(0)
        observed_at = datetime(*member.date_time, tzinfo=UTC)
        return ingest.run(FETCHER, run_ref, records(workbook, observed_at, erratum=name.startswith(RELEASE_4_0)))
