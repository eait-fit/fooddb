"""CIQUAL, the French food composition table (ANSES), under the Licence Ouverte / Etalab 2.0: about
3,500 generic foods, values per 100 g. A new release comes every few years, as an Excel file."""

import re
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import httpx

from fooddb import ingest
from fooddb.fetchers import download

PAGE = "https://ciqual.anses.fr/cms/en/node/20"
FETCHER = "ciqual"
LICENCE = "etalab-2.0"
ATTRIBUTION = "Anses. Ciqual French food composition table (https://ciqual.anses.fr). Licence Ouverte / Etalab 2.0."
RELEASE = re.compile(r"https?://[^\"'\s]*Table%20Ciqual%20\d{4}_ENG_(\d{4})_(\d{2})_(\d{2})\.xlsx")

# CIQUAL column (with "/" read as a space) → INFOODS tagname, as the table's own "INFOODS codes" sheet
# maps them. "Carbohydrate" is available carbohydrate (CHOAVL). "Fibres" is total dietary fibre (AOAC).
COLUMNS = {
    "Energy, Regulation EU No 1169 2011 (kJ 100g)": "ENERC_KJ",
    "Energy, Regulation EU No 1169 2011 (kcal 100g)": "ENERC_KCAL",
    "Protein (g 100g)": "PROCNT",
    "Carbohydrate (g 100g)": "CHOAVL",
    "Fat (g 100g)": "FAT",
    "Sugars (g 100g)": "SUGAR",
    "Fibres (g 100g)": "FIBTG",
    "FA saturated (g 100g)": "FASAT",
    "Sodium (mg 100g)": "NA",
}
GROUPS = ("alim_grp_nom_eng", "alim_ssgrp_nom_eng", "alim_ssssgrp_nom_eng")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def value(cell: str | None) -> float | None:
    """A CIQUAL cell as a number. "traces" is 0. "< x" (under the limit x) and "-" (no data) give no value."""
    s = (cell or "").strip()
    if s == "traces":
        return 0.0
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _column(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def rows(xlsx) -> Iterator[list[str | None]]:
    """The cells of the first sheet as text, row by row. The sheet is parsed as a stream."""
    with zipfile.ZipFile(xlsx) as z:
        with z.open("xl/sharedStrings.xml") as f:
            strings = ["".join(t.text or "" for t in si.iter(f"{NS}t"))
                       for _, si in ET.iterparse(f) if si.tag == f"{NS}si"]
        with z.open("xl/worksheets/sheet1.xml") as f:
            for _, row in ET.iterparse(f):
                if row.tag != f"{NS}row":
                    continue
                cells: dict[int, str | None] = {}
                for c in row.iter(f"{NS}c"):
                    v = c.findtext(f"{NS}v")
                    kind = c.get("t")
                    cells[_column(c.get("r"))] = (
                        strings[int(v)] if kind == "s" and v is not None
                        else "".join(t.text or "" for t in c.iter(f"{NS}t")) if kind == "inlineStr" else v)
                row.clear()
                yield [cells.get(i) for i in range(max(cells, default=-1) + 1)]


def records(xlsx, observed_at: datetime):
    it = rows(xlsx)
    at = {" ".join((h or "").replace("/", " ").split()): i for i, h in enumerate(next(it))}
    if missing := [c for c in (*COLUMNS, *GROUPS, "alim_code", "alim_nom_eng") if c not in at]:
        raise RuntimeError(f"ciqual: columns {missing} missing; the file layout changed")
    for row in it:
        def cell(name: str) -> str:
            return (row[at[name]] if at[name] < len(row) else None) or ""

        values = {tag: v for col, tag in COLUMNS.items() if (v := value(cell(col))) is not None}
        code, name = cell("alim_code").strip(), cell("alim_nom_eng").strip()
        if not code or not name or not values:
            continue
        yield ingest.Record(
            id=f"ciqual:{code}", source="ciqual", layer="core", licence=LICENCE, name=name, lang="en",
            values=values, observed_at=observed_at,
            categories=[f"ciqual:{g}" for col in GROUPS if (g := cell(col).strip()) not in ("", "-")],
        )


def newest(page: str) -> tuple[str, datetime]:
    """The newest English Excel release linked from the download page, and its date."""
    found = {m.group(0): datetime(*map(int, m.groups()), tzinfo=UTC) for m in RELEASE.finditer(page)}
    if not found:
        raise RuntimeError(f"ciqual: no release linked from {PAGE}; the page layout changed")
    return max(found.items(), key=lambda kv: kv[1])


def fetch(force: bool = False) -> tuple[int, int] | None:
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url, observed_at = newest(r.text)
    ref = url.rsplit("/", 1)[1]
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as tmp:
        download(url, tmp)
        return ingest.run(FETCHER, ref, records(tmp, observed_at))
