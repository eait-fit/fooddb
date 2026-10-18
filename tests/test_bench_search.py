import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bench_search",
                                              Path(__file__).parents[1] / "scripts" / "bench_search.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_percentile_interpolates_and_handles_small_samples():
    assert bench.pct([], 50) is None
    assert bench.pct([5.0], 95) == 5.0
    assert bench.pct([1, 2, 3, 4], 50) == 2.5
    assert bench.pct([1, 2, 3, 4], 95) == 3.85
    assert bench.pct([10, 1, 7], 50) == 7  # input order does not matter


def _item(pid=1, records=("fdc:1",), name="Rye bread", source="fdc", kcal=220.0):
    return {"id": pid, "records": list(records),
            "name": {"value": name, "source": source} if name else None,
            "per_100": {"ENERC_KCAL": {"value": kcal}} if kcal is not None else {}}


def test_acceptable_by_product_record_and_name():
    assert bench.acceptable(_item(pid=7), {"products": [7]})
    assert bench.acceptable(_item(records=["bls:B1"]), {"records": ["bls:B1"]})
    assert not bench.acceptable(_item(records=["bls:B1"]), {"records": ["bls:B2"]})
    assert bench.acceptable(_item(), {"name": "rye"})
    assert not bench.acceptable(_item(name=None), {"name": "rye"})
    assert bench.acceptable(_item(source="bls"), {"name": "rye", "source": "bls"})
    assert not bench.acceptable(_item(source="fdc"), {"name": "rye", "source": "bls"})
    # A source without a name pattern accepts any item that has a record of it.
    assert bench.acceptable(_item(records=["off:1", "fdc:2"]), {"source": "fdc"})
    assert not bench.acceptable(_item(records=["off:1"]), {"source": "fdc"})


def _result(hit1, found=1.0, search_p95=100.0, lookup_p95=50.0, hit5=None):
    m = {"hit1": hit1, "hit5": hit5 if hit5 is not None else hit1, "found": found,
         "kcal_median_pct": 5.0,
         "search_ms": {"p95": search_p95}, "lookup_ms": {"p95": lookup_p95}}
    return {"countries": {"de": m}, "overall": dict(m)}


def test_metrics():
    cases = [{"hit1": True, "hit5": True, "kcal_err_pct": 2.0, "ms": 10.0},
             {"hit1": False, "hit5": True, "kcal_err_pct": 10.0, "ms": 20.0},
             {"hit1": False, "hit5": False, "kcal_err_pct": None, "ms": 30.0}]
    lookups = [{"found": True, "ok": True, "expected_not_found": False, "ms": 5.0},
               {"found": False, "ok": True, "expected_not_found": True, "ms": 6.0},
               {"found": False, "ok": False, "expected_not_found": False, "ms": 7.0}]
    m = bench.metrics(cases, lookups)
    assert m["queries"] == 3 and m["hit1"] == 1 / 3 and m["hit5"] == 2 / 3
    assert m["kcal_n"] == 2 and m["kcal_median_pct"] == 6.0
    assert m["found"] == 0.5           # the expected-404 case is not a miss
    assert m["barcode_ok"] == 2 / 3    # but it still counts as correctly answered
    assert m["search_ms"] == {"n": 3, "p50": 20.0, "p95": 29.0, "max": 30.0}


def test_compare_quiet_within_thresholds():
    assert bench.compare(_result(0.80, search_p95=100.0), _result(0.76, search_p95=140.0)) == []


def test_compare_flags_hit_and_latency_regressions():
    bad = bench.compare(_result(0.80, search_p95=100.0, lookup_p95=40.0),
                        _result(0.70, search_p95=160.0))
    assert any("hit1" in line and "-10.0 pp" in line for line in bad)
    assert any("search_ms p95" in line for line in bad)
    assert not any("lookup_ms" in line for line in bad)


def test_compare_uses_both_country_and_overall():
    a = {"countries": {"de": _result(0.9)["overall"], "fr": _result(0.9)["overall"]},
         "overall": _result(0.9)["overall"]}
    b = {"countries": {"de": _result(0.9)["overall"], "fr": _result(0.5)["overall"]},
         "overall": _result(0.7)["overall"]}
    bad = bench.compare(a, b)
    assert any(line.startswith("fr") for line in bad)
    assert any(line.startswith("overall") for line in bad)


def test_compare_tolerates_new_countries_and_missing_metrics():
    a = {"countries": {"de": _result(0.9)["overall"]}, "overall": _result(0.9)["overall"]}
    b = {"countries": {"de": _result(0.9)["overall"], "kz": _result(0.1)["overall"]},
         "overall": _result(0.9)["overall"]}
    assert bench.compare(a, b) == []  # a country that only exists in the new run is not a regression
