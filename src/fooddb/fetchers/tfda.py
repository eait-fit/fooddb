"""The Taiwan food nutrient database (Taiwan Food and Drug Administration), under the Open Government Data
License, version 1.0: about 2,100 foods, values per 100 g, with Chinese names. The open data record on
data.gov.tw links a zip with one CSV in a long layout: one row for each food and analyte."""

import csv
import io
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta, timezone

import httpx

from fooddb import ingest
from fooddb.fetchers import download

PAGE = "https://data.gov.tw/api/v2/rest/dataset/8543"
FETCHER = "tfda"
LICENCE = "OGDL-Taiwan-1.0"
ATTRIBUTION = ("Food and Drug Administration, Ministry of Health and Welfare, Taiwan: Food Nutrient Dataset "
               "(食品營養成分資料集, https://data.gov.tw/dataset/8543). Made available to the public under the Open "
               "Government Data License, version 1.0 (https://data.gov.tw/license).")
TAIPEI = timezone(timedelta(hours=8))
SAMPLE = "樣品基本資料"  # a measured sample. 樣品平均值 rows are means of those samples, so they add nothing.

# 分析項 (analyte) → (its unit, INFOODS tagname). The unit must match, or the run stops. 總碳水化合物 is
# carbohydrate by difference, fibre included: it equals 100 minus water, ash, protein, fat and alcohol (the
# median gap over 2,212 foods is 0), so CHOCDF. 糖質總量 is the sum of the six sugars of the 糖質分析 group:
# glucose, fructose, galactose, sucrose, maltose and lactose (the largest gap over 1,212 foods is 0.2), so
# SUGAR. 熱量 follows 4 kcal/g of protein and of total carbohydrate and 9 kcal/g of fat (median gap 0.3 kcal).
# 修正熱量 (modified energy) is another figure and is left out.
ANALYTES = {
    "熱量": ("kcal", "ENERC_KCAL"), "粗蛋白": ("g", "PROCNT"), "粗脂肪": ("g", "FAT"), "總碳水化合物": ("g", "CHOCDF"),
    "糖質總量": ("g", "SUGAR"), "膳食纖維": ("g", "FIBTG"), "飽和脂肪": ("g", "FASAT"), "鈉": ("mg", "NA"),
}
COLUMNS = ("整合編號", "樣品名稱", "食品分類", "資料類別", "分析項", "含量單位", "每100克含量")


def records(zipped, observed_at: datetime):
    """Fold the long CSV into one record for each food. A blank amount is no value."""
    foods: dict[str, tuple[str, str, dict[str, float]]] = {}
    with zipfile.ZipFile(zipped) as z, z.open(next(n for n in z.namelist() if n.endswith(".csv"))) as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
        if missing := [c for c in COLUMNS if c not in (reader.fieldnames or [])]:
            raise RuntimeError(f"tfda: columns {missing} missing; the file layout changed")
        for row in reader:
            if row["資料類別"] != SAMPLE:
                continue
            _, _, values = foods.setdefault(row["整合編號"], (row["樣品名稱"].strip(), row["食品分類"].strip(), {}))
            if row["分析項"] in ANALYTES:
                unit, tag = ANALYTES[row["分析項"]]
                if row["含量單位"] != unit:
                    raise RuntimeError(f"tfda: {row['分析項']} is in {row['含量單位']!r}, not {unit!r}; the file layout changed")
                try:
                    values[tag] = float(row["每100克含量"])
                except ValueError:
                    pass
    for code, (name, group, values) in foods.items():
        if code and name and values:
            yield ingest.Record(
                id=f"tfda:{code}", source="tfda", layer="core", licence=LICENCE, name=name, lang="zh-TW",
                values=values, observed_at=observed_at, categories=[f"tfda:{group}"] if group else [],
            )


def newest(record: dict) -> tuple[str, str, datetime]:
    """The CSV zip in the data.gov.tw record, its ref (the record's modification time, in Taipei time) and that time."""
    result = record["result"]
    url = next((d["resourceDownloadUrl"] for d in result["distribution"] if d.get("resourceFormat") == "CSV"), None)
    if url is None:
        raise RuntimeError(f"tfda: no CSV in {PAGE}; the record layout changed")
    ref = result["modifiedDate"]
    return url, ref, datetime.fromisoformat(ref).replace(tzinfo=TAIPEI).astimezone(UTC)


def fetch(force: bool = False) -> tuple[int, int] | None:
    r = httpx.get(PAGE, timeout=60, follow_redirects=True)
    r.raise_for_status()
    url, ref, observed_at = newest(r.json())
    if not force and ingest.already_done(FETCHER, ref):
        return None
    with tempfile.TemporaryFile() as tmp:
        download(url, tmp)
        return ingest.run(FETCHER, ref, records(tmp, observed_at))
