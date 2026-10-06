"""The Standard Tables of Food Composition in Japan, 8th revised edition, 2023 supplement (MEXT): about
2,500 generic foods, values per 100 g of edible part. The ministry lets anyone use the data if they cite the
source. The main table is an Excel file whose address carries its date."""

import re
import tempfile
from datetime import UTC, datetime

import httpx

from fooddb import ingest
from fooddb.fetchers import download
from fooddb.fetchers.xlsx import rows

PAGE = "https://www.mext.go.jp/a_menu/syokuhinseibun/mext_00001.html"
FETCHER = "mext"
LICENCE = "mext-free-use"
EDITION = "日本食品標準成分表（八訂）増補2023年"
ATTRIBUTION = (f"{EDITION}から引用 (Standard Tables of Food Composition in Japan, 8th revised edition, 2023 supplement, "
               f"Ministry of Education, Culture, Sports, Science and Technology, {PAGE}).")
SHEET = "表全体"

# MEXT component identifier (the row under the units) → INFOODS tagname. Units: energy kJ and kcal, sodium mg,
# the rest g. A trailing "-" in an identifier only marks how MEXT derived the value. CHOAVL is available
# carbohydrate by mass (利用可能炭水化物, 質量計): fibre is not in it. CHOAVLM, the same in monosaccharide
# equivalents, is left out. CHOCDF is carbohydrate by difference (炭水化物), fibre included. FIB- is total
# dietary fibre (食物繊維総量, AOAC 2011.25). PROT- is protein from nitrogen. FAT- is total lipid.
COLUMNS = {
    "ENERC": "ENERC_KJ", "ENERC_KCAL": "ENERC_KCAL", "PROT-": "PROCNT", "FAT-": "FAT", "CHOAVL": "CHOAVL",
    "CHOCDF-": "CHOCDF", "FIB-": "FIBTG", "NA": "NA",
}
CLASS = re.compile(r"^(?:[＜（][^＞）]*[＞）]\s*)+")  # the class headings that lead some food names: ＜魚類＞ （あじ類）


def value(cell: str | None) -> float | None:
    """A MEXT cell as a number. "Tr" (trace) is 0. A number in brackets, "(11.3)" or "(0)", is an estimate that
    the table prints as its value, so it is the value. A dagger after a number points to a note. "-" (not
    measured) and a blank give no value."""
    s = (cell or "").strip().removesuffix("†")
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    if s == "Tr":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def records(xlsx, observed_at: datetime):
    at = None
    for row in rows(xlsx, SHEET):
        def cell(i: int) -> str | None:
            return row[i] if i < len(row) else None

        if at is None:
            if "成分識別子" in (cell(3) or ""):
                at = {v: i for i, v in enumerate(row) if v}
                if missing := [c for c in COLUMNS if c not in at]:
                    raise RuntimeError(f"mext: identifiers {missing} missing; the file layout changed")
            continue
        number, name = (cell(1) or "").strip(), " ".join((cell(3) or "").split())
        values = {tag: v for col, tag in COLUMNS.items() if (v := value(cell(at[col]))) is not None}
        if not re.fullmatch(r"\d{5}", number) or not name or not values:
            continue
        yield ingest.Record(
            id=f"mext:{number}", source="mext", layer="core", licence=LICENCE, name=CLASS.sub("", name) or name,
            lang="ja", values=values, observed_at=observed_at, categories=[f"mext:{cell(0) or number[:2]}"],
        )
    if at is None:
        raise RuntimeError(f"mext: no row of component identifiers in {SHEET!r}; the file layout changed")


def newest(page: str) -> tuple[str, str, datetime]:
    """The main table (第2章（データ）) on the MEXT page: its address, its ref (the file name, which starts
    with a date) and that date. The ATTRIBUTION names one edition, so another edition stops the run."""
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    if not title or EDITION not in title.group(1):
        raise RuntimeError(f"mext: {PAGE} is not the 8th edition, 2023 supplement any more; check its terms and ATTRIBUTION")
    m = re.search(r'href="(/content/(\d{8})-[^"]*\.xlsx)">・第2章（データ）', page)
    if not m:
        raise RuntimeError(f"mext: no main table on {PAGE}; the page layout changed")
    url = "https://www.mext.go.jp" + m.group(1)
    return url, url.rsplit("/", 1)[1], datetime.strptime(m.group(2), "%Y%m%d").replace(tzinfo=UTC)


def fetch(force: bool = False) -> tuple[int, int] | None:
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url, ref, observed_at = newest(r.text)
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as tmp:
        download(url, tmp)
        return ingest.run(FETCHER, ref, records(tmp, observed_at))
