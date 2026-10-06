"""Fineli, the Finnish food composition database (THL), under CC BY 4.0: about 4,200 generic foods,
values per 100 g of edible part. Its open data package is a zip of semicolon-separated CSV files."""

import csv
import io
import os
import tempfile
import zipfile
from datetime import UTC, datetime

from fooddb import ingest
from fooddb.fetchers import download

# Basic package 1: every food, 55 components. The site sits behind a Cloudflare challenge, which
# refused automated requests on 2026-10-06; a mirror of the zip can be set here.
URL = os.environ.get("FOODDB__BACKEND__FINELI_URL") or "https://fineli.fi/fineli/content/file/47"
FETCHER = "fineli"
LICENCE = "CC-BY-4.0"
ATTRIBUTION = "Finnish Institute for Health and Welfare (THL), Fineli (https://fineli.fi). CC BY 4.0."
KJ_PER_KCAL = 4.184

# Fineli EUFDNAME → INFOODS tagname. Units as Fineli states them: energy kJ, sodium mg, the rest g.
# CHOAVL is available carbohydrate. FIBC is total dietary fibre. Fineli states energy in kJ only.
NUTRIENTS = {
    "ENERC": "ENERC_KJ", "CHOAVL": "CHOAVL", "FAT": "FAT", "PROT": "PROCNT", "FIBC": "FIBTG",
    "SUGAR": "SUGAR", "FASAT": "FASAT", "NA": "NA",
}


def _csv(z: zipfile.ZipFile, name: str):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")


def records(z: zipfile.ZipFile):
    values: dict[str, dict[str, float]] = {}
    for row in _csv(z, "component_value.csv"):
        if (tag := NUTRIENTS.get(row["EUFDNAME"])) and row["BESTLOC"]:
            values.setdefault(row["FOODID"], {})[tag] = float(row["BESTLOC"].replace(",", "."))
    names = {row["FOODID"]: row["FOODNAME"].strip() for row in _csv(z, "foodname_EN.csv")}
    observed_at = datetime(*z.getinfo("component_value.csv").date_time, tzinfo=UTC)
    for food in _csv(z, "food.csv"):
        v, name = values.get(food["FOODID"]), names.get(food["FOODID"])
        if not v or not name:
            continue
        if "ENERC_KJ" in v:
            v["ENERC_KCAL"] = v["ENERC_KJ"] / KJ_PER_KCAL
        yield ingest.Record(
            id=f"fineli:{food['FOODID']}", source="fineli", layer="core", licence=LICENCE, name=name, lang="en",
            values=v, observed_at=observed_at,
            categories=[f"fineli:{c}" for c in (food["FUCLASS"], food["FUCLASSP"]) if c],
        )


def fetch(force: bool = False) -> tuple[int, int] | None:
    """The package has no release name in its URL: its SHA-256 is the ref, so a re-published
    package loads once."""
    with tempfile.TemporaryFile() as tmp:
        ref = download(URL, tmp)
        if not force and ingest.already_done(FETCHER, ref):
            return None
        with zipfile.ZipFile(tmp) as z:
            return ingest.run(FETCHER, ref, records(z))
