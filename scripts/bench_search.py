"""Search and barcode benchmark for fooddb (issue #94).

Runs the committed golden sets in bench/search/<country>.json against a fooddb base URL — prod by
default — and scores, per country and overall: hit@1 and hit@5 on the generic-food queries, the
top-1 answer's kcal error against the case's cited reference (median and p90 over the cases whose
top-1 has a kcal value), the barcode found-rate, and p50/p95/max latency for search and for lookup.
Writes bench/results/<UTC date>-<server id>.json where the id is the sha /version or /livez
reports, else the API version. Every request is a GET: the benchmark never writes.

    set -a; . ~/.config/fooddb/bench.env; set +a   # FOODDB__BENCH__URL, FOODDB__BENCH__KEY
    uv run python scripts/bench_search.py [--country de,fr] [--base-url URL]
    uv run python scripts/bench_search.py --compare [A B]      # default: the last two results

--compare prints per-country and overall deltas and exits 1 on a regression past THRESHOLDS.

A query case names its acceptable answers in "expect": "records" (record ids like "bls:B221000")
or "products" (product ids) the answer must hold one of, or a "name" regex the answer's name must
match (with "source" pinning which record may name it). "kcal" is the reference kcal/100 g and
"kcal_ref" its citation. A barcode case carries the same "expect" or "not_found": true. Every
case's "why" says what makes it representative.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "bench" / "search"
RESULTS = ROOT / "bench" / "results"
PROD = "https://food-api.eait.fit"

# Regression bars for --compare, all in one place: a run fails when a country's or the overall
# hit@1/hit@5/found-rate drops by more than *_drop_pp percentage points, or a p95 latency is
# multiplied past p95_growth.
THRESHOLDS = {"hit1_drop_pp": 5.0, "hit5_drop_pp": 5.0, "found_drop_pp": 5.0, "p95_growth": 1.5}


def pct(xs: list[float], p: float) -> float | None:
    """Linear-interpolated percentile; None on an empty sample."""
    if not xs:
        return None
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def acceptable(item: dict, expect: dict) -> bool:
    """An item is acceptable when a listed product id or record id is its, or when its name matches
    the pattern (named by a record of "source" when one is pinned)."""
    if item.get("id") in expect.get("products", ()):
        return True
    if set(item.get("records", ())) & set(expect.get("records", ())):
        return True
    name = item.get("name") or {}
    if (pattern := expect.get("name")) and re.search(pattern, name.get("value") or "", re.I):
        if (source := expect.get("source")) is None or name.get("source") == source:
            return True
    if "name" not in expect and (source := expect.get("source")):
        return any(str(r).startswith(source + ":") for r in item.get("records", ()))
    return False


def kcal_of(item: dict) -> float | None:
    v = (item.get("per_100") or {}).get("ENERC_KCAL")
    return v["value"] if v else None


def get(client: httpx.Client, path: str, **params) -> tuple[httpx.Response, float]:
    """One GET, retried on 429 and 5xx; (response, milliseconds of the last attempt)."""
    ms = 0.0
    for attempt in range(3):
        t = time.perf_counter()
        try:
            r = client.get(path, params=params)
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(2.0)
            continue
        ms = (time.perf_counter() - t) * 1000
        if r.status_code != 429 and r.status_code < 500 or attempt == 2:
            return r, ms
        time.sleep(float(r.headers.get("retry-after") or 2.0 * (attempt + 1)))
    raise AssertionError("unreachable")


def server_id(client: httpx.Client) -> dict:
    """What is answering: sha from /version or /livez, else the API version; plus the snapshot day."""
    info = {"version": None, "sha": None, "snapshot": None}
    for path in ("/version", "/livez"):
        try:
            r = client.get(path)
        except httpx.HTTPError:
            continue
        if r.status_code == 200:
            body = r.json()
            info["sha"] = info["sha"] or body.get("sha") or body.get("commit")
            info["version"] = info["version"] or body.get("version")
    try:
        r = client.get("/v1/snapshots")
        if r.status_code == 200 and (items := r.json().get("items")):
            info["snapshot"] = items[0].get("day")
    except httpx.HTTPError:
        pass
    info["id"] = ((info["sha"] or "")[:12] or
                  (f"v{info['version']}" if info["version"] else
                   f"snap-{info['snapshot']}" if info["snapshot"] else "unknown"))
    return info


def run_query(client: httpx.Client, country: str, case: dict) -> dict:
    r, ms = get(client, "/v1/foods", q=case["q"], country=country, limit=5)
    items = r.json().get("items", []) if r.status_code == 200 else []
    hit1 = bool(items) and acceptable(items[0], case["expect"])
    hit5 = any(acceptable(i, case["expect"]) for i in items)
    top_kcal = kcal_of(items[0]) if items else None
    ref = case.get("kcal")
    err = abs(top_kcal - ref) / ref * 100 if top_kcal is not None and ref else None
    return {"q": case["q"], "status": r.status_code, "ms": ms, "hit1": hit1, "hit5": hit5,
            "top_id": items[0]["id"] if items else None, "top_kcal": top_kcal,
            "kcal_err_pct": err, "ids": [i["id"] for i in items]}


def run_barcode(client: httpx.Client, country: str, case: dict) -> dict:
    r, ms = get(client, f"/v1/products/{case['barcode']}", include="off", country=country)
    items = r.json().get("items", []) if r.status_code == 200 else []
    if case.get("not_found"):
        ok = r.status_code == 404
    else:
        ok = r.status_code == 200 and any(acceptable(i, case.get("expect", {})) for i in items)
    return {"barcode": case["barcode"], "status": r.status_code, "ms": ms, "ok": ok,
            "found": r.status_code == 200, "expected_not_found": bool(case.get("not_found")),
            "top_id": items[0]["id"] if items else None}


def ms_stats(xs: list[float]) -> dict:
    return {"n": len(xs), "p50": pct(xs, 50), "p95": pct(xs, 95), "max": max(xs, default=None)}


def metrics(cases: list[dict], lookups: list[dict]) -> dict:
    errs = [c["kcal_err_pct"] for c in cases if c["kcal_err_pct"] is not None]
    wanted = [b for b in lookups if not b["expected_not_found"]]
    return {
        "queries": len(cases),
        "hit1": sum(c["hit1"] for c in cases) / len(cases) if cases else None,
        "hit5": sum(c["hit5"] for c in cases) / len(cases) if cases else None,
        "kcal_n": len(errs),
        "kcal_median_pct": pct(errs, 50),
        "kcal_p90_pct": pct(errs, 90),
        "barcodes": len(lookups),
        "found": sum(b["found"] for b in wanted) / len(wanted) if wanted else None,
        "barcode_ok": sum(b["ok"] for b in lookups) / len(lookups) if lookups else None,
        "search_ms": ms_stats([c["ms"] for c in cases]),
        "lookup_ms": ms_stats([b["ms"] for b in lookups]),
    }


def run(base: str, key: str | None, only: set[str] | None) -> dict:
    client = httpx.Client(base_url=base, timeout=30.0,
                          headers={"Authorization": f"Bearer {key}"} if key else {})
    server = server_id(client)
    out = {"date": datetime.now(UTC).date().isoformat(),
           "server": {"url": base, **server}, "countries": {}}
    all_cases, all_lookups = [], []
    for path in sorted(GOLDEN.glob("*.json")):
        gold = json.loads(path.read_text())
        country = gold["country"]
        if only and country not in only:
            continue
        print(f"{country} ({path.name})", flush=True)
        cases, lookups = [], []
        for case in gold.get("queries", []):
            cases.append(run_query(client, country, case))
            print(f"  {case['q']!r}: hit@1={cases[-1]['hit1']} {cases[-1]['ms']:.0f} ms", flush=True)
        for case in gold.get("barcodes", []):
            lookups.append(run_barcode(client, country, case))
            print(f"  {case['barcode']}: {lookups[-1]['status']} {lookups[-1]['ms']:.0f} ms", flush=True)
        out["countries"][country] = {**metrics(cases, lookups), "cases": cases, "barcode_cases": lookups}
        all_cases += cases
        all_lookups += lookups
    out["overall"] = metrics(all_cases, all_lookups)
    return out


def result_path(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    return RESULTS / (name if name.endswith(".json") else name + ".json")


def compare(a: dict, b: dict) -> list[str]:
    """Regression lines where b (new) falls past THRESHOLDS under a (old); empty means no regression."""
    bad = []
    keys = sorted(set(a["countries"]) | set(b["countries"])) + ["overall"]
    for cc in keys:
        old = a["overall"] if cc == "overall" else a["countries"].get(cc)
        new = b["overall"] if cc == "overall" else b["countries"].get(cc)
        if not old or not new:
            continue
        for key, drop in (("hit1", "hit1_drop_pp"), ("hit5", "hit5_drop_pp"),
                          ("found", "found_drop_pp")):
            if old.get(key) is not None and new.get(key) is not None and \
                    (new[key] - old[key]) * 100 <= -THRESHOLDS[drop]:
                bad.append(f"{cc} {key}: {old[key]:.3f} -> {new[key]:.3f} "
                           f"({(new[key] - old[key]) * 100:+.1f} pp)")
        for lat in ("search_ms", "lookup_ms"):
            o, n = old.get(lat, {}).get("p95"), new.get(lat, {}).get("p95")
            if o and n and n / o >= THRESHOLDS["p95_growth"]:
                bad.append(f"{cc} {lat} p95: {o:.0f} -> {n:.0f} ms (x{n / o:.2f})")
    return bad


def print_deltas(a: dict, b: dict) -> None:
    cols = ("hit@1 %", "hit@5 %", "kcal med %", "found %", "search p95 ms", "lookup p95 ms")
    print(f"{'':10}" + " ".join(f"{c:>22}" for c in cols))
    for cc in sorted(set(a["countries"]) | set(b["countries"])) + ["overall"]:
        old = a["overall"] if cc == "overall" else a["countries"].get(cc)
        new = b["overall"] if cc == "overall" else b["countries"].get(cc)
        if not old or not new:
            continue
        cells = []
        for key in ("hit1", "hit5", "kcal_median_pct", "found"):
            o, n = old.get(key), new.get(key)
            scale = 1.0 if key == "kcal_median_pct" else 100.0
            cells.append("n/a" if o is None or n is None else f"{o * scale:.0f} -> {n * scale:.0f}")
        for lat in ("search_ms", "lookup_ms"):
            o, n = old.get(lat, {}).get("p95"), new.get(lat, {}).get("p95")
            cells.append("n/a" if o is None or n is None else f"{o:.0f} -> {n:.0f}")
        print(f"{cc:10}" + " ".join(f"{c:>22}" for c in cells))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=os.environ.get("FOODDB__BENCH__URL", PROD))
    ap.add_argument("--country", help="comma list to run only some countries")
    ap.add_argument("--compare", nargs="*", metavar="RESULT",
                    help="compare two result files (default: the last two) instead of running")
    ap.add_argument("--out", help="result file path (default bench/results/<date>-<id>.json)")
    args = ap.parse_args()

    if args.compare is not None:
        pair = args.compare or [f.name for f in sorted(RESULTS.glob("*.json"))[-2:]]
        if len(pair) != 2:
            sys.exit(f"--compare needs two results; {RESULTS} has {len(pair)} to compare")
        a, b = (json.loads(result_path(p).read_text()) for p in pair)
        print_deltas(a, b)
        bad = compare(a, b)
        for line in bad:
            print(f"REGRESSION {line}")
        return 1 if bad else 0

    key = os.environ.get("FOODDB__BENCH__KEY")
    if not key:
        sys.exit("FOODDB__BENCH__KEY is not set: a read key, from the environment only")
    result = run(args.base_url.rstrip("/"), key,
                 set(args.country.split(",")) if args.country else None)
    out = Path(args.out) if args.out else RESULTS / f"{result['date']}-{result['server']['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    o = result["overall"]
    found = f"{o['found']:.1%}" if o["found"] is not None else "n/a"
    print(f"\nwrote {out}\n"
          f"overall: hit@1 {o['hit1']:.1%}  hit@5 {o['hit5']:.1%}  "
          f"kcal err med {o['kcal_median_pct']}% p90 {o['kcal_p90_pct']}%  "
          f"found {found}  search p95 {o['search_ms']['p95']:.0f} ms  "
          f"lookup p95 {o['lookup_ms']['p95']:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
