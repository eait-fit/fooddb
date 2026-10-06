"""Parsers of the national tables and FDC Branded, on trimmed samples of each publisher's real files."""

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fooddb import checks

FIXTURES = Path(__file__).parent / "fixtures"


def test_json_items_streams_a_top_level_array_in_small_reads():
    from fooddb.fetchers.fdc import json_items

    doc = '{"meta": {"n": [1, 2]}, "Foods": [ {"a": "x, ]}"}, {"b": [1, {"c": 2}]} ,{"d": "\\u00e9"} ]}'
    f = io.BytesIO(doc.encode())
    assert list(json_items(f, "Foods", chunk=3)) == [{"a": "x, ]}"}, {"b": [1, {"c": 2}]}, {"d": "é"}]
    assert list(json_items(io.BytesIO(b'{"Foods": []}'), "Foods")) == []


def test_fdc_branded_records_carry_barcode_brand_serving_and_category(tmp_path):
    from fooddb.fetchers import fdc

    path = tmp_path / "branded.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.write(FIXTURES / "fdc_branded.json", "FoodData_Central_branded_food_json_2026-04-30.json")
    with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as f:
        granola, water, soda = fdc.records(fdc.json_items(f, "BrandedFoods"))
    assert granola.id == "fdc:1106281" and granola.licence == "CC0-1.0" and granola.layer == "core"
    assert granola.gtin14 == "01633636543505" and granola.brand == "MICHELE'S"
    assert (granola.serving_text, granola.serving_g, granola.basis) == ("0.25 cup", 28, "100g")
    assert granola.values == {"PROCNT": 10.7, "FAT": 25.0, "CHOCDF": 57.1, "SUGAR": 21.4, "FASAT": 7.14,
                              "FIBTG": 7.1, "NA": 161, "ENERC_KCAL": 500}
    assert granola.categories == ["Cereal"] and granola.observed_at == datetime(2020, 11, 13, tzinfo=UTC)
    # Drinks state their values per 100 ml; a serving in ml has no gram weight.
    assert (soda.basis, soda.serving_g, soda.serving_text) == ("100ml", None, "1 BOTTLE")
    assert checks.category(soda.categories) == "beverages"
    assert checks.category(water.categories) == "beverages"  # FDC files sweetened sparkling waters under Water
    assert water.gtin14 == "00083046155385"


def test_fdc_branded_is_off_by_default(monkeypatch):
    from fooddb import health

    monkeypatch.delenv("FOODDB__BACKEND__FETCH_FDC_BRANDED", raising=False)
    assert not health.enabled("fdc-branded") and "fdc-branded" not in health.watched()
    monkeypatch.setenv("FOODDB__BACKEND__FETCH_FDC_BRANDED", "true")
    assert health.enabled("fdc-branded") and "fdc-branded" in health.watched()
    assert health.enabled("ciqual")


def test_ciqual_values_follow_the_conservative_rule_for_traces_and_bounds():
    from fooddb.fetchers.ciqual import value

    assert value("4,41") == 4.41 and value("1070") == 1070 and value(" 6.25 ") == 6.25
    assert value("traces") == 0
    assert value("< 0,5") is None and value("-") is None and value("") is None and value(None) is None


def test_ciqual_reads_the_xlsx_into_available_carbohydrate_and_its_groups():
    from fooddb.fetchers import ciqual

    observed = datetime(2025, 11, 3, tzinfo=UTC)
    dessert, celeriac, tuna = ciqual.records(FIXTURES / "ciqual.xlsx", observed)
    assert dessert.id == "ciqual:24999" and dessert.name == "Dessert (average)" and dessert.lang == "en"
    assert dessert.licence == "etalab-2.0" and dessert.source == "ciqual" and dessert.layer == "core"
    assert dessert.values == {"ENERC_KJ": 1070, "ENERC_KCAL": 255, "PROCNT": 4.41, "CHOAVL": 32.9, "FAT": 11.3,
                              "SUGAR": 21.3, "FIBTG": 1.7, "FASAT": 4.96, "NA": 130}
    assert dessert.categories == [] and dessert.observed_at == observed
    assert celeriac.categories == ["ciqual:starters and dishes", "ciqual:mixed salads"]
    assert "CHOCDF" not in tuna.values and tuna.values["CHOAVL"] == 8.13
    assert checks.category(["ciqual:fruits, vegetables, legumes and nuts", "ciqual:vegetables"]) == "vegetables"


def test_ciqual_finds_the_newest_release_on_its_download_page():
    from fooddb.fetchers import ciqual

    page = ('<a href="https://ciqual.anses.fr/cms/sites/default/files/inline-files/Table%20Ciqual%202025_ENG_2025_11_03.xlsx">'
            '<a href="https://ciqual.anses.fr/cms/sites/default/files/inline-files/Table%20Ciqual%202020_ENG_2020_07_07.xlsx">'
            '<a href="https://ciqual.anses.fr/cms/sites/default/files/inline-files/Table%20Ciqual%202025_FR_2025_11_03.xlsx">')
    url, observed = ciqual.newest(page)
    assert url.endswith("Table%20Ciqual%202025_ENG_2025_11_03.xlsx") and observed == datetime(2025, 11, 3, tzinfo=UTC)


def test_fineli_reads_its_csv_package_into_available_carbohydrate_and_kcal():
    from fooddb.fetchers import fineli

    with zipfile.ZipFile(FIXTURES / "fineli.zip") as z:
        sugar, fructose = fineli.records(z)
    assert sugar.id == "fineli:1" and sugar.name == "SUGAR" and sugar.licence == "CC-BY-4.0"
    assert sugar.values == {"ENERC_KJ": 1698.3, "CHOAVL": 99.9, "FAT": 0, "PROCNT": 0, "FIBTG": 0, "SUGAR": 99.9,
                            "FASAT": 0, "NA": 0.1, "ENERC_KCAL": 1698.3 / 4.184}
    assert sugar.categories == ["fineli:SUGADD", "fineli:SUGARTOT"] and checks.category(sugar.categories) == "sweets"
    assert fructose.name == "FRUCTOSE"
    assert sugar.observed_at.tzinfo is UTC


def test_matvaretabellen_reads_its_food_list_into_available_carbohydrate():
    from fooddb.fetchers import fdc, matvaretabellen

    observed = datetime(2026, 10, 6, tzinfo=UTC)
    with open(FIXTURES / "matvaretabellen.json", "rb") as f:
        beans, agave, aioli = matvaretabellen.records(fdc.json_items(f, "foods"), observed)
    assert beans.id == "matvaretabellen:06.178" and beans.name == "Adzuki beans, uncooked"
    assert beans.licence == "NLOD-2.0" and beans.layer == "core" and beans.observed_at == observed
    assert beans.values == {"ENERC_KJ": 1312.4, "ENERC_KCAL": 310, "FAT": 0.5, "FASAT": 0.2, "CHOAVL": 50.2,
                            "SUGAR": 3.0, "FIBTG": 13.0, "PROCNT": 19.9, "NA": 5.0}
    assert beans.categories == ["matvaretabellen:12"] and checks.category(beans.categories) == "legumes"
    assert agave.categories == ["matvaretabellen:7.1", "matvaretabellen:7"]
    assert checks.category(aioli.categories) == "fats"  # 8.3 mayonnaise, under 8 cooking fat: not an oil
    assert not checks.flags(beans.values, checks.category(beans.categories))


def test_frida_reads_its_data_table_with_both_carbohydrate_codes_and_its_food_groups():
    from fooddb.fetchers import frida

    observed = datetime(2026, 1, 19, tzinfo=UTC)
    strawberry, biscuit, celeriac, water = frida.records(FIXTURES / "frida.xlsx", observed)
    assert strawberry.id == "frida:1" and strawberry.name == "Strawberry, raw" and strawberry.lang == "en"
    assert strawberry.licence == "CC-BY-4.0" and strawberry.source == "frida" and strawberry.layer == "core"
    assert strawberry.values == pytest.approx({
        "ENERC_KJ": 161.95358974359, "ENERC_KCAL": 38.4579487179487, "PROCNT": 0.659855769230769,
        "CHOCDF": 8.34732371794872, "CHOAVL": 6.8619391025641, "FIBTG": 1.48538461538462, "FAT": 0.6,
        "SUGAR": 6.06625, "FASAT": 0.049655172413793, "NA": 0.5078})
    assert strawberry.observed_at == observed
    assert strawberry.values["CHOCDF"] == pytest.approx(strawberry.values["CHOAVL"] + strawberry.values["FIBTG"])
    assert strawberry.categories == ["frida:51", "frida:47"] and checks.category(strawberry.categories) == "fruits"
    assert "FASAT" not in biscuit.values and biscuit.categories == ["frida:32", "frida:126"]
    assert "SUGAR" not in celeriac.values and celeriac.values["FIBTG"] > 0
    assert water.values["ENERC_KCAL"] == 0 and checks.category(water.categories) == "waters"
    assert not checks.flags(strawberry.values, "fruits")


def test_frida_stops_when_a_parameter_is_not_the_one_it_expects(tmp_path):
    from fooddb.fetchers import frida

    broken = tmp_path / "frida.xlsx"
    with zipfile.ZipFile(FIXTURES / "frida.xlsx") as src, zipfile.ZipFile(broken, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            out.writestr(item, data.replace(b"Available carbohydrates", b"Starch") if "sharedStrings" in item.filename else data)
    with pytest.raises(RuntimeError, match="parameter 172"):
        list(frida.records(broken, datetime(2026, 1, 19, tzinfo=UTC)))


def test_frida_finds_the_dataset_workbook_in_the_dtu_data_record():
    from fooddb.fetchers import frida

    article = {"version": 8, "published_date": "2026-01-19T12:00:51Z", "files": [
        {"name": "Frida5.5_Documentation_English.pdf", "computed_md5": "47", "download_url": "https://ndownloader.figshare.com/files/60901597"},
        {"name": "Frida_5.5_Dataset.xlsx", "computed_md5": "b553eed6805e3cd8856663421de0f1fe", "download_url": "https://ndownloader.figshare.com/files/60901603"},
        {"name": "Frida_5.5_Dataset.ods", "computed_md5": "06", "download_url": "https://ndownloader.figshare.com/files/60901606"}]}
    url, ref, observed = frida.newest(article)
    assert url == "https://ndownloader.figshare.com/files/60901603" and ref == "Frida_5.5_Dataset.xlsx b553eed6805e3cd8856663421de0f1fe"
    assert observed == datetime(2026, 1, 19, 12, 0, 51, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="no dataset workbook"):
        frida.newest({"files": [article["files"][0]]})
