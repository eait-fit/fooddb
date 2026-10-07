"""The Standard Tables of Food Composition in Japan, 8th revised edition, 2023 supplement (MEXT): about
2,500 generic foods, values per 100 g of edible part. The ministry lets anyone use the data if they cite the
source. The main table is an Excel file whose address carries its date. Total sugars and saturated fat are in
two supplementary tables of the same page, joined to the main table on the food number."""

import re
import tempfile
from collections.abc import Iterable, Iterator
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
# dietary fibre (食物繊維総量, AOAC 2011.25). PROT- is protein from nitrogen. FAT- is total lipid. ALC is
# alcohol (アルコール) in g.
COLUMNS = {
    "ENERC": "ENERC_KJ", "ENERC_KCAL": "ENERC_KCAL", "PROT-": "PROCNT", "FAT-": "FAT", "CHOAVL": "CHOAVL",
    "CHOCDF-": "CHOCDF", "FIB-": "FIBTG", "NA": "NA", "ALC": "ALC",
}
# The supplementary tables, one workbook each with the same sheet and rows of identifiers. Both state g per 100 g
# of edible part. FASAT is saturated fatty acids (飽和脂肪酸) in the fatty acid book (脂肪酸成分表編), 第1表. The
# carbohydrate book (炭水化物成分表編), 本表, lists the sugars each in its own mass: GLUS glucose, FRUS fructose,
# GALS galactose, SUCS sucrose, MALS maltose, LACS lactose and TRES trehalose. SUGAR is their sum, the mono- and
# disaccharides, as for Frida. A "-" (not measured) adds nothing. STARCH, the sugar alcohols (SORTL, MANTL) and
# CHOAVLM (monosaccharide equivalents) are not sugars here.
FATTY_ACIDS = "FASAT"
SUGARS = ("GLUS", "FRUS", "GALS", "SUCS", "MALS", "LACS", "TRES")
UNIT = "g/100 g"
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


def _table(xlsx, ids: Iterable[str], unit: str | None = None) -> Iterator[tuple[str, str, str, dict[str, float]]]:
    """(food number, name, group, {identifier: value}) of each food in the sheet. A blank or "-" cell is not in the
    dict. With `unit`, the row under the identifiers must state it for each identifier."""
    ids = tuple(ids)
    at, check_units = None, False
    for row in rows(xlsx, SHEET):
        def cell(i: int) -> str | None:
            return row[i] if i < len(row) else None

        if at is None:
            if "成分識別子" in (cell(3) or ""):
                at = {v: i for i, v in enumerate(row) if v}
                if missing := [c for c in ids if c not in at]:
                    raise RuntimeError(f"mext: identifiers {missing} missing; the file layout changed")
                check_units = unit is not None
            continue
        if check_units:
            if wrong := [c for c in ids if " ".join((cell(at[c]) or "").split()) != unit]:
                raise RuntimeError(f"mext: {wrong[0]} is not in {unit!r}, so the unit changed; the file layout changed")
            check_units = False
            continue
        number, name = (cell(1) or "").strip(), " ".join((cell(3) or "").split())
        if re.fullmatch(r"\d{5}", number) and name:
            yield number, name, cell(0) or number[:2], {c: v for c in ids if (v := value(cell(at[c]))) is not None}
    if at is None:
        raise RuntimeError(f"mext: no row of component identifiers in {SHEET!r}; the file layout changed")


def _supplements(foods: dict[str, str], fatty_acids, carbohydrates) -> dict[str, dict[str, float]]:
    """SUGAR and FASAT for each food number. The same number must name the same food in every table."""
    out: dict[str, dict[str, float]] = {}

    def read(xlsx, ids: tuple[str, ...], tag: str, combine) -> None:
        for number, name, _, v in _table(xlsx, ids, UNIT) if xlsx is not None else ():
            if number in foods and foods[number] != name:
                raise RuntimeError(f"mext: {number} is {name!r} here and {foods[number]!r} in the main table; the numbering changed")
            if v:
                out.setdefault(number, {})[tag] = combine(v.values())

    read(fatty_acids, (FATTY_ACIDS,), "FASAT", sum)
    read(carbohydrates, SUGARS, "SUGAR", lambda parts: round(sum(parts), 2))
    return out


def records(xlsx, observed_at: datetime, fatty_acids=None, carbohydrates=None):
    """The main table, with FASAT and SUGAR from the two supplementary tables when they are given."""
    foods = list(_table(xlsx, COLUMNS))
    extra = _supplements({n: name for n, name, _, _ in foods}, fatty_acids, carbohydrates)
    for number, name, group, v in foods:
        values = {COLUMNS[c]: x for c, x in v.items()} | extra.get(number, {})
        if values:
            yield ingest.Record(
                id=f"mext:{number}", source="mext", layer="core", licence=LICENCE, name=CLASS.sub("", name) or name,
                lang="ja", values=values, observed_at=observed_at, categories=[f"mext:{group}"],
            )


def newest(page: str) -> tuple[tuple[str, str, str], str, datetime]:
    """The addresses of the main table (第2章（データ）), the fatty acid table (脂肪酸成分表編, 第2章第1表) and the
    carbohydrate table (炭水化物成分表編, 第2章本表) on the MEXT page, their ref (the file names, which start with a
    date, joined with "+") and the newest of those dates. The ATTRIBUTION names one edition, so another edition
    stops the run."""
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    if not title or EDITION not in title.group(1):
        raise RuntimeError(f"mext: {PAGE} is not the 8th edition, 2023 supplement any more; check its terms and ATTRIBUTION")
    link = r'href="(/content/(\d{8})-[^"]*\.xlsx)">'
    found = []
    for what, pattern in (("main table", link + "・第2章（データ）"),
                          ("fatty acid table", "脂肪酸成分表編.*?" + link + "・第2章第1表（データ）"),
                          ("carbohydrate table", "炭水化物成分表編.*?" + link + "・第2章本表（データ）")):
        m = re.search(pattern, page, re.S)
        if not m:
            raise RuntimeError(f"mext: no {what} on {PAGE}; the page layout changed")
        found.append(m.groups())
    urls = tuple("https://www.mext.go.jp" + path for path, _ in found)
    observed = max(datetime.strptime(d, "%Y%m%d").replace(tzinfo=UTC) for _, d in found)
    return urls, "+".join(u.rsplit("/", 1)[1] for u in urls), observed


def fetch(force: bool = False) -> tuple[int, int] | None:
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    urls, ref, observed_at = newest(r.text)
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as main, tempfile.TemporaryFile() as fatty_acids, tempfile.TemporaryFile() as carbohydrates:
        for url, tmp in zip(urls, (main, fatty_acids, carbohydrates)):
            download(url, tmp)
        return ingest.run(FETCHER, ref, records(main, observed_at, fatty_acids, carbohydrates))
