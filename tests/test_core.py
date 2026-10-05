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
    assert checks.flags({"ENERC_KCAL": 100, "PROCNT": 10, "FAT": 5, "CHOCDF": 10}) == []
    assert "energy-mismatch" in checks.flags({"ENERC_KCAL": 900, "PROCNT": 10, "FAT": 5, "CHOCDF": 10})
    assert "macros-over-100g" in checks.flags({"PROCNT": 60, "FAT": 30, "CHOCDF": 30})
    assert "sugars-over-carbs" in checks.flags({"CHOCDF": 10, "SUGAR": 20})


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
