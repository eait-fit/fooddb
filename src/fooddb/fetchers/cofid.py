"""CoFID, McCance and Widdowson's Composition of Foods Integrated Dataset (Public Health England), under the
Open Government Licence v3.0: about 2,900 generic foods, values per 100 g, or per 100 ml for alcoholic
beverages. The last release is from 2021. It is an Excel workbook with a sheet for each group of nutrients."""

import tempfile
from datetime import datetime

import httpx

from fooddb import ingest
from fooddb.fetchers import download
from fooddb.fetchers.xlsx import rows

PAGE = "https://www.gov.uk/api/content/government/publications/composition-of-foods-integrated-dataset-cofid"
FETCHER = "cofid"
LICENCE = "OGL-UK-3.0"
ATTRIBUTION = ("McCance and Widdowson's The Composition of Foods Integrated Dataset 2021, Public Health England "
               "(https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid). "
               "Contains public sector information licensed under the Open Government Licence v3.0.")

# CoFID tagname (row 2 of each sheet) → INFOODS tagname. Units as the sheets state them: energy kJ and kcal,
# sodium mg, the rest g per 100 g. AOACFIB is total dietary fibre by AOAC. ENGFIB (Englyst NSP) is another
# method and is left out. SATFOD is saturated fatty acids per 100 g of food (SATFAC is per 100 g of fat).
# CHO and TOTSUG are left out: the user guide states them as monosaccharide equivalents, which is about 5 %
# more than the weight of available carbohydrate and sugars, and it gives only an approximate factor. That is
# neither CHOAVL nor CHOCDF. ALCO is ethanol in g, per 100 ml for the alcoholic beverages like the rest of their row.
PROXIMATES = ("1.3 Proximates", {"PROT": "PROCNT", "FAT": "FAT", "KCALS": "ENERC_KCAL", "KJ": "ENERC_KJ",
                                  "AOACFIB": "FIBTG", "SATFOD": "FASAT", "ALCO": "ALC"})
INORGANICS = ("1.4 Inorganics", {"NA": "NA"})


def value(cell: str | None) -> float | None:
    """A CoFID cell as a number. "Tr" (trace) is 0. "N" (significant, but no reliable value) and a blank give no value."""
    s = (cell or "").strip()
    if s == "Tr":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def _foods(xlsx, sheet: str, columns: dict[str, str]):
    """(food code, name, group, values) for each row of a sheet. Rows 1 to 3 are the headings: the names,
    the tagnames and the descriptions."""
    it = rows(xlsx, sheet)
    names, tags, _ = next(it), next(it), next(it)
    at = {t: i for i, t in enumerate(tags) if t}
    if missing := [t for t in columns if t not in at] + [h for i, h in ((1, "Food Name"), (3, "Group")) if names[i:i + 1] != [h]]:
        raise RuntimeError(f"cofid: {sheet!r} lacks {missing}; the file layout changed")
    for row in it:
        def cell(i: int) -> str | None:
            return row[i] if i < len(row) else None

        yield (cell(0) or "").strip(), (cell(1) or "").strip(), (cell(3) or "").strip(), {
            tag: v for col, tag in columns.items() if (v := value(cell(at[col]))) is not None}


def records(xlsx, observed_at: datetime):
    sodium = {code: values for code, _, _, values in _foods(xlsx, *INORGANICS)}
    foods: dict[str, ingest.Record | None] = {}
    for code, name, group, values in _foods(xlsx, *PROXIMATES):
        values |= sodium.get(code, {})
        # CoFID 2021 gives one code (13-669) to two foods. Neither can be told from the other, so neither is kept.
        foods[code] = None if code in foods or not (code and name and values) else ingest.Record(
            id=f"cofid:{code}", source="cofid", layer="core", licence=LICENCE, name=name, lang="en",
            values=values, observed_at=observed_at, basis="100ml" if group.startswith("Q") else "100g",
            categories=[f"cofid:{group[:n]}" for n in range(len(group), 0, -1)],
        )
    yield from (r for r in foods.values() if r)


def newest(content: dict) -> tuple[str, str, datetime]:
    """The workbook of the integrated dataset on the gov.uk page: its address, its ref (the asset id in the
    address) and the day of the newest change. The page also lists a user guide and a file of old foods."""
    details = content["details"]
    url = next((a["url"] for a in details["attachments"]
                if a["url"].endswith(".xlsx") and "old foods" not in a["title"].lower()), None)
    if url is None:
        raise RuntimeError(f"cofid: no dataset workbook on {PAGE}; the page layout changed")
    return url, url.rsplit("/", 2)[1], datetime.fromisoformat(details["change_history"][0]["public_timestamp"])


def fetch(force: bool = False) -> tuple[int, int] | None:
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url, ref, observed_at = newest(r.json())
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as tmp:
        download(url, tmp)
        return ingest.run(FETCHER, ref, records(tmp, observed_at))
