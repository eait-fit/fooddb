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


def test_tfda_folds_its_long_csv_into_one_record_per_food_with_total_carbohydrate_and_sugars():
    from fooddb.fetchers import tfda

    observed = datetime(2026, 10, 4, 16, 34, 48, tzinfo=UTC)
    got = {r.id: r for r in tfda.records(FIXTURES / "tfda.zip", observed)}
    assert sorted(got) == ["tfda:D3200301", "tfda:D3200404", "tfda:J0200201", "tfda:M9900201", "tfda:O0101301"]  # no D21002
    apple, fuji, shark, oil, juice = got["tfda:D3200301"], got["tfda:D3200404"], got["tfda:J0200201"], got["tfda:M9900201"], got["tfda:O0101301"]
    assert apple.name == "美國五爪蘋果" and apple.lang == "zh-TW" and apple.observed_at == observed
    assert apple.licence == "OGDL-Taiwan-1.0" and apple.source == "tfda" and apple.layer == "core" and apple.basis == "100g"
    # Sugars (糖質總量) and saturated fat are blank for this sample: no value. Modified energy (修正熱量) and water are not mapped.
    assert apple.values == pytest.approx({"ENERC_KCAL": 51, "PROCNT": 0.2, "FAT": 0.1, "CHOCDF": 13.8, "FIBTG": 1.6, "NA": 2})
    assert fuji.values == pytest.approx({"ENERC_KCAL": 49, "PROCNT": 0.2, "FAT": 0.1, "CHOCDF": 13.1, "SUGAR": 10.4, "FIBTG": 1.3,
                                         "FASAT": 0.0, "NA": 3})
    assert shark.values["ENERC_KCAL"] == 117 and shark.values["CHOCDF"] == 0 and "FIBTG" not in shark.values and "SUGAR" not in shark.values
    assert oil.values["FAT"] == 100.3 and oil.values["FASAT"] == 17.0  # a fat above 100 g is the table's value
    assert juice.values["SUGAR"] == 11.1 and "CHOAVL" not in juice.values
    assert apple.categories == ["tfda:水果類"] and checks.category(apple.categories) == "fruits"
    assert checks.category(shark.categories) == "fish" and checks.category(oil.categories) == "fats"
    assert checks.category(juice.categories) == "beverages"
    assert not checks.flags(fuji.values, "fruits") and not checks.flags(oil.values, "fats")


def test_tfda_stops_when_an_analyte_changes_its_unit_or_a_column_goes(tmp_path):
    from fooddb.fetchers import tfda

    with zipfile.ZipFile(FIXTURES / "tfda.zip") as z:
        text = z.read(z.namelist()[0]).decode("utf-8")

    def broken(name: str, data: str) -> Path:
        with zipfile.ZipFile(tmp_path / name, "w") as out:
            out.writestr("20_2.csv", data.encode("utf-8"))
        return tmp_path / name

    with pytest.raises(RuntimeError, match="熱量"):
        list(tfda.records(broken("unit.zip", text.replace('"熱量","kcal"', '"熱量","kJ"')), datetime(2026, 10, 5, tzinfo=UTC)))
    with pytest.raises(RuntimeError, match="整合編號"):
        list(tfda.records(broken("column.zip", text.replace("整合編號", "編號", 1)), datetime(2026, 10, 5, tzinfo=UTC)))


def test_tfda_finds_the_csv_zip_in_the_data_gov_tw_record():
    from fooddb.fetchers import tfda

    record = {"success": True, "result": {"modifiedDate": "2026-10-05 08:34:48", "distribution": [
        {"resourceFormat": "CSV", "resourceDownloadUrl": "https://data.fda.gov.tw/data/opendata/export/20/csv"},
        {"resourceFormat": "JSON", "resourceDownloadUrl": "https://data.fda.gov.tw/data/opendata/export/20/json"}]}}
    url, ref, observed = tfda.newest(record)
    assert url == "https://data.fda.gov.tw/data/opendata/export/20/csv" and ref == "2026-10-05 08:34:48"
    assert observed == datetime(2026, 10, 5, 0, 34, 48, tzinfo=UTC)  # the record gives Taipei time
    with pytest.raises(RuntimeError, match="no CSV"):
        tfda.newest({"result": {"modifiedDate": "2026-10-05 08:34:48", "distribution": record["result"]["distribution"][1:]}})


def test_cofid_value_follows_the_conservative_rule_for_trace_and_not_measured():
    from fooddb.fetchers.cofid import value

    assert value("151") == 151 and value("0.30") == 0.3 and value(" 5.1 ") == 5.1
    assert value("Tr") == 0
    assert value("N") is None and value("") is None and value(None) is None


def test_cofid_reads_its_sheets_and_leaves_out_carbohydrate_in_monosaccharide_equivalents():
    from fooddb.fetchers import cofid

    observed = datetime(2021, 3, 19, 14, 0, 7, tzinfo=UTC)
    ackee, agar, allspice, apples, beer = cofid.records(FIXTURES / "cofid.xlsx", observed)
    assert ackee.id == "cofid:13-145" and ackee.name == "Ackee, canned, drained" and ackee.lang == "en"
    assert ackee.licence == "OGL-UK-3.0" and ackee.source == "cofid" and ackee.layer == "core"
    # Fat 15.2, energy and sodium are stated. Saturates are N (not measured), AOAC fibre is blank. Carbohydrate is not stored.
    assert ackee.values == {"PROCNT": 2.9, "FAT": 15.2, "ENERC_KCAL": 151, "ENERC_KJ": 625, "NA": 240}
    assert agar.values["FASAT"] == 0.3 and "FIBTG" not in agar.values
    assert allspice.values == {"PROCNT": 6.1, "FAT": 8.7, "FASAT": 2.5, "NA": 77}  # N for energy: no value
    assert apples.values == {"PROCNT": 0.6, "FAT": 0.5, "ENERC_KCAL": 51, "ENERC_KJ": 215, "FIBTG": 1.2, "FASAT": 0.12, "NA": 1}
    assert not any(k in v.values for v in (ackee, agar, allspice, apples, beer) for k in ("CHOAVL", "CHOCDF", "SUGAR"))
    assert beer.values["FAT"] == 0 and beer.values["FIBTG"] == 0 and beer.values["FASAT"] == 0  # Tr is 0
    assert apples.basis == "100g" and beer.basis == "100ml"  # alcoholic beverages are per 100 ml
    assert apples.observed_at == observed
    assert apples.categories == ["cofid:FA", "cofid:F"] and checks.category(apples.categories) == "fruits"
    assert beer.categories == ["cofid:QA", "cofid:Q"] and checks.category(beer.categories) == "alcoholic-beverages"
    assert ackee.categories == ["cofid:DG", "cofid:D"] and checks.category(ackee.categories) is None
    assert not checks.flags(apples.values, "fruits")


def test_cofid_drops_a_food_code_that_two_foods_share():
    from fooddb.fetchers import cofid

    ids = [r.id for r in cofid.records(FIXTURES / "cofid.xlsx", datetime(2021, 3, 19, tzinfo=UTC))]
    assert "cofid:13-669" not in ids and len(ids) == 5  # CoFID 2021 gives 13-669 to an aubergine and to watercress


def test_cofid_stops_when_a_tagname_moves(tmp_path):
    from fooddb.fetchers import cofid

    broken = tmp_path / "cofid.xlsx"
    with zipfile.ZipFile(FIXTURES / "cofid.xlsx") as src, zipfile.ZipFile(broken, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            out.writestr(item, data.replace(b">AOACFIB<", b">AOACFIBRE<") if "sharedStrings" in item.filename else data)
    with pytest.raises(RuntimeError, match="AOACFIB"):
        list(cofid.records(broken, datetime(2021, 3, 19, tzinfo=UTC)))


def test_cofid_finds_the_dataset_workbook_on_its_gov_uk_page():
    from fooddb.fetchers import cofid

    base = "https://assets.publishing.service.gov.uk/media/"
    content = {"details": {"change_history": [{"public_timestamp": "2021-03-19T14:00:07Z"}, {"public_timestamp": "2019-03-25T12:30:00Z"}],
                           "attachments": [
        {"title": "McCance and Widdowson’s The Composition of Foods Integrated Dataset 2021: user guide",
         "content_type": "application/pdf", "url": base + "60538e66d3bf7f03249bac58/guide.pdf"},
        {"title": "McCance and Widdowson's composition of foods: old foods",
         "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "url": base + "60538ba4e90e07527f645f88/CoFID_oldFoods.xlsx"},
        {"title": "McCance and Widdowson's composition of foods integrated dataset",
         "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "url": base + "60538b91e90e07527df82ae4/McCance_Widdowsons_Composition_of_Foods_Integrated_Dataset_2021..xlsx"}]}}
    url, ref, observed = cofid.newest(content)
    assert url.endswith("McCance_Widdowsons_Composition_of_Foods_Integrated_Dataset_2021..xlsx")
    assert ref == "60538b91e90e07527df82ae4" and observed == datetime(2021, 3, 19, 14, 0, 7, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="no dataset workbook"):
        cofid.newest({"details": {"change_history": [], "attachments": content["details"]["attachments"][:2]}})


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


def test_mext_value_follows_the_rule_for_estimates_traces_and_gaps():
    from fooddb.fetchers.mext import value

    assert value("12.7") == 12.7 and value("1452") == 1452 and value(" 0.3 ") == 0.3
    assert value("(11.3)") == 11.3 and value("(0)") == 0  # an estimate is the table's value
    assert value("Tr") == 0 and value("(Tr)") == 0
    assert value("18.5†") == 18.5  # † points to a note on the value
    assert value("-") is None and value("*") is None and value("") is None and value(None) is None


def test_mext_reads_its_main_table_with_available_carbohydrate_and_clean_japanese_names():
    from fooddb.fetchers import mext

    observed = datetime(2026, 3, 27, tzinfo=UTC)
    got = {r.id: r for r in mext.records(FIXTURES / "mext.xlsx", observed)}
    assert list(got) == ["mext:01001", "mext:01172", "mext:01026", "mext:01091", "mext:03032", "mext:07107", "mext:09059",
                         "mext:10457", "mext:14011", "mext:16001"]
    amaranth, batter, bread, porridge, syrup, banana, wakame, horse_mackerel, oil, sake = got.values()
    assert "FASAT" not in bread.values and "SUGAR" not in bread.values  # the main table has neither
    assert amaranth.name == "アマランサス 玄穀" and amaranth.lang == "ja" and amaranth.observed_at == observed
    assert amaranth.licence == "mext-free-use" and amaranth.source == "mext" and amaranth.layer == "core"
    assert amaranth.values == pytest.approx({"ENERC_KJ": 1452, "ENERC_KCAL": 343, "PROCNT": 12.7, "FAT": 6.0, "CHOAVL": 57.8,
                                             "CHOCDF": 64.9, "FIBTG": 7.4, "NA": 1})
    assert amaranth.categories == ["mext:01"] and checks.category(amaranth.categories) is None
    assert "CHOAVL" not in batter.values and batter.values["FAT"] == pytest.approx(47.7)  # "-": not measured
    assert porridge.values["PROCNT"] == 1.1 and porridge.values["NA"] == 0 and porridge.values["CHOAVL"] == 14.2  # (1.1), (Tr)
    assert syrup.values["CHOAVL"] == 18.5 and syrup.values["FIBTG"] == 14.0 and syrup.values["FAT"] == 0  # 18.5†, Tr
    assert syrup.name == "還元水あめ"
    assert wakame.values == {"ENERC_KJ": 1, "ENERC_KCAL": 0, "CHOCDF": 0.1, "FIBTG": 0, "NA": 68}
    assert horse_mackerel.name == "にしまあじ 開き干し 生" and horse_mackerel.values["CHOAVL"] == 0
    assert "FIBTG" not in horse_mackerel.values and checks.category(horse_mackerel.categories) == "fish"
    assert oil.values["FAT"] == 100 and "CHOAVL" not in oil.values and checks.category(oil.categories) == "fats"
    assert checks.category(banana.categories) == "fruits" and checks.category(sake.categories) == "beverages"
    assert not checks.flags(banana.values, "fruits") and not checks.flags(oil.values, "fats")


def mext_with_supplements():
    from fooddb.fetchers import mext

    return {r.id: r for r in mext.records(FIXTURES / "mext.xlsx", datetime(2026, 3, 27, tzinfo=UTC),
                                          FIXTURES / "mext_fatty_acids.xlsx", FIXTURES / "mext_carbohydrates.xlsx")}


def test_mext_joins_saturated_fat_and_the_sum_of_its_sugars_by_food_number():
    got = mext_with_supplements()
    assert list(got) == ["mext:01001", "mext:01172", "mext:01026", "mext:01091", "mext:03032", "mext:07107", "mext:09059",
                         "mext:10457", "mext:14011", "mext:16001"]
    amaranth, batter, bread, porridge, syrup, banana, wakame, horse_mackerel, oil, sake = got.values()
    # The main table's values stay as they were.
    assert amaranth.values == pytest.approx({"ENERC_KJ": 1452, "ENERC_KCAL": 343, "PROCNT": 12.7, "FAT": 6.0, "CHOAVL": 57.8,
                                             "CHOCDF": 64.9, "FIBTG": 7.4, "NA": 1, "FASAT": 1.18, "SUGAR": 1.3})
    # Sugars are the sum of glucose, fructose, galactose, sucrose, maltose, lactose and trehalose, each in its own mass.
    # A "-" (not measured, as galactose is for bread) adds nothing, and "Tr" is 0.
    assert bread.values["FASAT"] == 1.5 and bread.values["SUGAR"] == pytest.approx(1.5 + 2.2 + 0 + 1.3 + 0.2 + 0.1)
    assert banana.values["SUGAR"] == pytest.approx(2.6 + 2.4 + 10.5) and banana.values["FASAT"] == 0.07  # (0.07): an estimate
    assert porridge.values["SUGAR"] == pytest.approx(0.2) and porridge.values["FASAT"] == 0.08
    # A food that a table does not list keeps no value for it. Zero is a value: the table measured it.
    assert "FASAT" not in syrup.values and syrup.values["SUGAR"] == 0
    assert "SUGAR" not in horse_mackerel.values and horse_mackerel.values["FASAT"] == 2.87
    assert "SUGAR" not in oil.values and oil.values["FASAT"] == 10.25
    assert sake.values["FASAT"] == 0 and sake.values["SUGAR"] == 2.5
    assert not {"FASAT", "SUGAR"} & (batter.values.keys() | wakame.values.keys())
    for food, category in ((banana, "fruits"), (oil, "fats")):
        assert not checks.flags(food.values, category)  # sugars stay under CHOAVL, saturates under fat


def test_mext_reads_the_main_table_alone_when_no_supplement_is_given():
    from fooddb.fetchers import mext

    bread = next(r for r in mext.records(FIXTURES / "mext.xlsx", datetime(2026, 3, 27, tzinfo=UTC)) if r.id == "mext:01026")
    assert "FASAT" not in bread.values and "SUGAR" not in bread.values


def broken_mext(tmp_path, source: str, old: str, new: str) -> Path:
    broken = tmp_path / source
    with zipfile.ZipFile(FIXTURES / source) as src, zipfile.ZipFile(broken, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            out.writestr(item, data.replace(f">{old}<".encode(), f">{new}<".encode()) if "sharedStrings" in item.filename else data)
    return broken


def test_mext_stops_when_a_supplementary_table_changes_its_identifier_unit_or_numbering(tmp_path):
    from fooddb.fetchers import mext

    at, main = datetime(2026, 3, 27, tzinfo=UTC), FIXTURES / "mext.xlsx"
    fa, carbs = FIXTURES / "mext_fatty_acids.xlsx", FIXTURES / "mext_carbohydrates.xlsx"
    with pytest.raises(RuntimeError, match="FASAT"):
        list(mext.records(main, at, broken_mext(tmp_path, "mext_fatty_acids.xlsx", "FASAT", "FASATX"), carbs))
    with pytest.raises(RuntimeError, match="TRES"):
        list(mext.records(main, at, fa, broken_mext(tmp_path, "mext_carbohydrates.xlsx", "TRES", "TRESX")))
    with pytest.raises(RuntimeError, match="FASAT.*unit"):
        list(mext.records(main, at, broken_mext(tmp_path, "mext_fatty_acids.xlsx", "g/100 g", "mg/100 g"), carbs))
    with pytest.raises(RuntimeError, match="GLUS.*unit"):
        list(mext.records(main, at, fa, broken_mext(tmp_path, "mext_carbohydrates.xlsx", "g/100 g", "mg/100 g")))
    # The same number must name the same food in every table, or the join would mix foods.
    with pytest.raises(RuntimeError, match="01001.*numbering"):
        list(mext.records(main, at, broken_mext(tmp_path, "mext_fatty_acids.xlsx", "アマランサス　玄穀", "あわ"), carbs))


def test_mext_stops_when_a_component_identifier_moves(tmp_path):
    from fooddb.fetchers import mext

    broken = tmp_path / "mext.xlsx"
    with zipfile.ZipFile(FIXTURES / "mext.xlsx") as src, zipfile.ZipFile(broken, "w") as out:
        for item in src.infolist():
            data = src.read(item)
            out.writestr(item, data.replace(b">CHOAVL<", b">CHOAVLX<") if "sharedStrings" in item.filename else data)
    with pytest.raises(RuntimeError, match="CHOAVL"):
        list(mext.records(broken, datetime(2026, 3, 27, tzinfo=UTC)))


def test_mext_finds_the_main_table_on_its_page_and_stops_when_the_edition_changes():
    from fooddb.fetchers import mext

    page = ('<html><head><title>日本食品標準成分表（八訂）増補2023年：文部科学省</title></head><body>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_0001.pdf">日本食品標準成分表（八訂）増補2023年 電子書籍（第2章を除く）&nbsp;(PDF:5.1MB)</a></li>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_02.xlsx">・第2章（データ）&nbsp;(Excel:1.9MB) <img alt="Excel"/></a></li>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_04.xlsx">・第2章第1表（データ）&nbsp;(Excel:915KB)</a></li>'
            '<li><a href="/content/20230428-mxt_kagsei-mext_00001_031.pdf">日本食品標準成分表（八訂）増補2023年脂肪酸成分表編　電子書籍（第2章を除く）&nbsp;(PDF:1.2MB)</a></li>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_09.xlsx">・第2章第1表（データ）&nbsp;(Excel:1.5MB)</a></li>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_10.xlsx">・第2章第2表（データ）&nbsp;(Excel:891KB)</a></li>'
            '<li><a href="/content/20230428-mxt_kagsei-mext_00001_041.pdf">日本食品標準成分表（八訂）増補2023年炭水化物成分表編　電子書籍（第2章を除く）&nbsp;(PDF:1.5MB)</a></li>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_13.xlsx">・第2章本表（データ）&nbsp;(Excel:312KB)</a></li>'
            '<li><a href="/content/20260327-mxt_kagsei-mext-000029402_14.xlsx">・第2章本表別表1（データ）&nbsp;(Excel:292KB)</a></li></body></html>')
    urls, ref, observed = mext.newest(page)
    names = [f"20260327-mxt_kagsei-mext-000029402_{n}.xlsx" for n in ("02", "09", "13")]
    assert urls == tuple("https://www.mext.go.jp/content/" + n for n in names)  # the first table of the fatty acid book, not of the amino acid book
    assert ref == "+".join(names) and observed == datetime(2026, 3, 27, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="edition"):
        mext.newest(page.replace("八訂）増補2023年：", "九訂）2030年："))
    with pytest.raises(RuntimeError, match="no main table"):
        mext.newest(page.replace("・第2章（データ）", "・第3章（データ）"))
    with pytest.raises(RuntimeError, match="no fatty acid table"):
        mext.newest(page.replace("_09.xlsx", "_09.pdf"))
    with pytest.raises(RuntimeError, match="no carbohydrate table"):
        mext.newest(page.replace("・第2章本表（データ）", "・第2章本表別表1（データ）"))
