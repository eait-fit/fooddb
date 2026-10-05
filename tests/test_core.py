from fooddb import checks, gtin


def test_gtin_normalizes_to_14_digits():
    assert gtin.normalize("4006381333931") == "04006381333931"  # EAN-13
    assert gtin.normalize("036000291452") == "00036000291452"  # UPC-A
    assert gtin.normalize("96385074") == "00000096385074"  # EAN-8


def test_gtin_rejects_bad_check_digit_and_junk():
    assert gtin.normalize("4006381333932") is None
    assert gtin.normalize("abc") is None
    assert gtin.normalize("123") is None
    assert gtin.normalize(None) is None


def test_gtin_rejects_store_local_prefixes():
    body = "2000000000001"[:-1]
    assert gtin.normalize(body + str(gtin.check_digit(body))) is None


def test_checks_flag_energy_mismatch_and_impossible_sums():
    assert not checks.flags({"ENERC_KCAL": 100, "PROCNT": 10, "FAT": 5, "CHOCDF": 10})
    assert "energy-mismatch" in checks.flags({"ENERC_KCAL": 900, "PROCNT": 10, "FAT": 5, "CHOCDF": 10})
    assert "macros-over-100g" in checks.flags({"PROCNT": 60, "FAT": 30, "CHOCDF": 30})
    assert "sugars-over-carbs" in checks.flags({"CHOCDF": 10, "SUGAR": 20})


def test_checks_name_the_fields_they_implicate():
    found = checks.flags({"ENERC_KCAL": 900, "PROCNT": 10, "FAT": 5, "CHOCDF": 10, "SUGAR": 20, "FIBTG": -1})
    assert found["energy-mismatch"] == {"ENERC_KCAL", "PROCNT", "FAT", "CHOCDF"}
    assert found["sugars-over-carbs"] == {"SUGAR", "CHOCDF"}
    assert found["negative-value"] == {"FIBTG"}


def test_off_reads_new_and_old_nutrition_schemas():
    from fooddb.fetchers.off import per_100

    new = {"nutrition": {"aggregated_set": {"per": "100g", "nutrients": {
        "energy-kcal": {"value": 383, "unit": "kcal"}, "sodium": {"value": 0.165, "unit": "g"},
        "fat": {"value": 500, "unit": "mg"}}}}}
    assert per_100(new) == {"ENERC_KCAL": 383, "NA": 165.0, "FAT": 0.5}
    old = {"nutriments": {"proteins_100g": "6.5", "sodium_100g": 0.2}}
    assert per_100(old) == {"PROCNT": 6.5, "NA": 200.0}


def test_off_catches_up_every_delta_after_the_last_done_one():
    from fooddb.fetchers.off import todo

    index = [f"openfoodfacts_products_{a}_{b}.json.gz" for a, b in [(1, 2), (2, 3), (3, 4), (4, 5)]]
    # Worker was down after delta 2→3: both later days come back, oldest first.
    assert todo(index, done={index[0], index[1]}, first_run=1) == index[2:]
    # Nothing done yet: only the newest `first_run` files.
    assert todo(index, done=set(), first_run=1) == index[-1:]
    # A delta that failed in between is retried even though newer ones are done.
    assert todo(index, done={index[0], index[2], index[3]}, first_run=1) == [index[1]]


def test_off_records_carry_basis_and_convert_kj_only_energy():
    import json

    from fooddb.fetchers.off import records

    drink = {"code": "5449000000996", "product_name": "Cola", "last_modified_t": 1790000000,
             "nutrition": {"aggregated_set": {"per": "100ml", "nutrients": {
                 "energy-kj": {"value": 180, "unit": "kJ"}, "sugars": {"value": 10.6, "unit": "g"}}}}}
    (r,) = records([json.dumps(drink)])
    assert r.basis == "100ml"
    assert round(r.values["ENERC_KCAL"], 1) == 43.0  # 180 kJ / 4.184


def off_product(countries: list[str] | None, nutrients: dict) -> dict:
    p = {"code": "4006381333931", "product_name": "Hummus", "last_modified_t": 1790000000,
         "nutrition": {"aggregated_set": {"per": "100g", "nutrients": nutrients}}}
    return p | ({"countries_tags": countries} if countries is not None else {})


def test_off_carbohydrate_code_follows_the_label_market():
    import json

    from fooddb.fetchers.off import records

    def carbs(countries, key="carbohydrates", flat=False):
        p = off_product(countries, {key: {"value": 14.9, "unit": "g"}})
        if flat:
            p = p | {"nutrition": {}, "nutriments": {f"{key}_100g": 14.9}}
        (r,) = records([json.dumps(p)])
        return [k for k in r.values if k.startswith("CHO")], r.extra_flags

    assert carbs(["en:germany"]) == (["CHOAVL"], [])
    assert carbs(["en:united-kingdom", "en:australia"], flat=True) == (["CHOAVL"], [])
    assert carbs(["en:united-states"]) == (["CHOCDF"], [])
    assert carbs(["en:canada"], flat=True) == (["CHOCDF"], [])
    assert carbs(["en:france"], key="carbohydrates-total") == (["CHOCDF"], [])  # the label says total
    assert carbs(["en:united-states", "en:france"]) == (["CHOCDF"], ["carbs-regime-unknown"])
    assert carbs(["en:japan"]) == (["CHOCDF"], ["carbs-regime-unknown"])
    assert carbs(None) == (["CHOCDF"], ["carbs-regime-unknown"])
    (r,) = records([json.dumps(off_product(None, {"energy-kcal": {"value": 229, "unit": "kcal"}}))])
    assert r.extra_flags == []  # no carbohydrate value, nothing to guess


def test_off_keeps_kj_as_stated_and_kcal_canonical():
    from fooddb.fetchers.off import per_100

    both = off_product(None, {"energy-kcal": {"value": 229, "unit": "kcal"}, "energy-kj": {"value": 958, "unit": "kJ"}})
    assert per_100(both) == {"ENERC_KCAL": 229, "ENERC_KJ": 958}
    kj_only = per_100(off_product(None, {"energy-kj": {"value": 180, "unit": "kJ"}}))
    assert kj_only["ENERC_KJ"] == 180 and round(kj_only["ENERC_KCAL"], 1) == 43.0
    flat = per_100({"nutriments": {"energy-kj_100g": 180}})
    assert flat["ENERC_KJ"] == 180 and round(flat["ENERC_KCAL"], 1) == 43.0


def test_fdc_maps_carbohydrate_by_difference_and_kj():
    from fooddb.fetchers.fdc import records

    def n(i, amount):
        return {"nutrient": {"id": i}, "amount": amount}

    payload = {"SRLegacyFoods": [{"fdcId": 1, "description": "Hummus", "publicationDate": "4/1/2019",
                                  "foodNutrients": [n(1005, 14.9), n(1008, 229), n(1062, 958), n(1050, 9.0)]}]}
    (r,) = records(payload, "SRLegacyFoods")
    assert r.values == {"CHOCDF": 14.9, "ENERC_KCAL": 229, "ENERC_KJ": 958}


def test_checks_use_the_carbohydrate_code_the_record_has():
    # Available carbohydrate excludes fibre: Atwater adds fibre at 2 kcal/g (EU 1169/2011 Annex XIV).
    assert not checks.flags({"ENERC_KCAL": 200, "PROCNT": 0, "FAT": 0, "CHOAVL": 20, "FIBTG": 60})
    found = checks.flags({"ENERC_KCAL": 200, "PROCNT": 0, "FAT": 0, "CHOAVL": 20, "SUGAR": 30})
    assert found["energy-mismatch"] == {"ENERC_KCAL", "PROCNT", "FAT", "CHOAVL"}
    assert found["sugars-over-carbs"] == {"SUGAR", "CHOAVL"}
    found = checks.flags({"ENERC_KCAL": 900, "PROCNT": 0, "FAT": 0, "CHOAVL": 20, "FIBTG": 60})
    assert found["energy-mismatch"] == {"ENERC_KCAL", "PROCNT", "FAT", "CHOAVL", "FIBTG"}
    assert checks.flags({"PROCNT": 60, "FAT": 30, "CHOAVL": 30})["macros-over-100g"] == {"PROCNT", "FAT", "CHOAVL"}
    # Carbohydrate by difference already holds the fibre: it is not counted twice.
    assert not checks.flags({"ENERC_KCAL": 80, "PROCNT": 0, "FAT": 0, "CHOCDF": 20, "FIBTG": 15})
