"""fooddb-review: work the fooddb review queue over the HTTP API, from any agent.

One stdlib-only file on purpose: copy it anywhere and run `python3 reviewcli.py …`, or install the
package and call `fooddb-review`. It talks to the REST API only and never touches the database.

Environment:
  FOODDB__REVIEW__KEY   an API key with the `review` scope (required; env only, never echoed)
  FOODDB__REVIEW__URL   the API's base URL (default https://food-api.eait.fit); --url wins
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://food-api.eait.fit"
KEY_ENV = "FOODDB__REVIEW__KEY"
URL_ENV = "FOODDB__REVIEW__URL"
TIMEOUT = 30

CHECKS = """\
A check name filters to the records whose values failed that check (the `checks` facet lists them
with counts): energy-mismatch (the declared calories disagree with the macros by Atwater),
macros-over-100g (protein + fat + carbohydrate over 105 g per 100 g), sugars-over-carbs,
saturates-over-fat, negative-value, out-of-range (a value outside its food group's range) and
seal-disagreement (a "high in …" seal on the pack that the values do not reach)."""

DECISIONS = """\
--accept marks the value accepted: the resolver may serve it from the next snapshot on. --reject
marks it rejected: it is never served. The decision is recorded under --by plus the key's name."""


def _request(base: str, key: str, method: str, path: str, params: dict | None = None,
             body: dict | None = None) -> tuple[int, object]:
    """One API call: (status, parsed JSON). A network or DNS failure raises URLError."""
    query = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else ""
    req = urllib.request.Request(
        base.rstrip("/") + path + query, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"authorization": f"Bearer {key}", "accept": "application/json"}
                | ({"content-type": "application/json"} if body is not None else {}))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except (ValueError, UnicodeDecodeError):
            return e.code, {"detail": str(e.reason)}


def _detail(body: object) -> str:
    return body.get("detail", body) if isinstance(body, dict) else str(body)


def _read(base: str, key: str, path: str, params: dict) -> int:
    """facets and queue: one GET, the JSON on stdout. Any refusal or failure exits non-zero."""
    try:
        status, body = _request(base, key, "GET", path, params)
    except urllib.error.URLError as e:
        print(f"fooddb-review: cannot reach {base}: {e.reason}", file=sys.stderr)
        return 1
    if status != 200:
        print(f"fooddb-review: {status} {_detail(body)}", file=sys.stderr)
        return 1
    print(json.dumps(body))
    return 0


def _decide(base: str, key: str, args) -> int:
    """One POST per id, one JSON line out per id. A refusal of the key or the server aborts the
    batch; a per-id refusal (not pending, not found) is reported on its line and skipped."""
    decision = "accept" if args.accept else "reject"
    body = {"decision": decision, "by": args.by} | ({"note": args.note} if args.note else {})
    for raw in args.ids:
        try:
            oid = int(raw)
        except ValueError:
            print(json.dumps({"id": raw, "error": "not an observation id"}))
            continue
        try:
            status, answer = _request(base, key, "POST", f"/v1/review/{oid}", body=body)
        except urllib.error.URLError as e:
            print(f"fooddb-review: cannot reach {base}: {e.reason}", file=sys.stderr)
            return 1
        if status in (401, 403):
            print(f"fooddb-review: {status} {_detail(answer)}", file=sys.stderr)
            return 1
        if status == 200:
            print(json.dumps(answer))
        elif status in (404, 409, 422):
            print(json.dumps({"id": oid, "error": _detail(answer)}))
        else:
            print(f"fooddb-review: {status} {_detail(answer)}", file=sys.stderr)
            return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    url = {"metavar": "URL", "help": f"the API's base URL (or ${URL_ENV}; default {DEFAULT_URL})"}
    p = argparse.ArgumentParser(
        prog="fooddb-review", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Work the fooddb review queue over the HTTP API: see what waits, then accept or "
                    f"reject values. The API key is read from ${KEY_ENV} — a key with the `review` "
                    f"scope — and is never echoed. The base URL is --url or ${URL_ENV} "
                    f"(default {DEFAULT_URL}).\n\n{CHECKS}\n\n{DECISIONS}")
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--url", **url)
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("facets", parents=[base], formatter_class=argparse.RawDescriptionHelpFormatter,
                       help="counts of the pending records, per check and per source",
                       epilog=CHECKS)
    f.add_argument("--source", metavar="S", help="one source (fdc, off, recipe, label, …)")
    f.add_argument("--check", metavar="C", help="one check name")
    q = sub.add_parser("queue", parents=[base], formatter_class=argparse.RawDescriptionHelpFormatter,
                       help="the records whose pending values wait for a decision",
                       epilog=CHECKS + "\n\nEach item is one source record: its pending values "
                       "(observation ids for `decide`), the values served now and its failed checks; "
                       "--detail adds every latest value and a line per check with its numbers.")
    q.add_argument("--source", metavar="S", help="one source (fdc, off, recipe, label, …)")
    q.add_argument("--check", metavar="C", help="one check name")
    q.add_argument("--limit", type=int, default=100, metavar="N", help="records at most (default 100)")
    q.add_argument("--offset", type=int, default=0, metavar="N", help="skip the first N records")
    q.add_argument("--detail", action="store_true", help="add each record's latest values and why")
    d = sub.add_parser("decide", parents=[base], formatter_class=argparse.RawDescriptionHelpFormatter,
                       help="accept or reject pending values, one JSON line per id",
                       epilog=DECISIONS + "\n\nA value already decided answers 409: it is reported "
                       "on its line and skipped, never fatal to the batch.")
    d.add_argument("ids", nargs="+", metavar="ID", help="observation ids from `queue`")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--accept", action="store_true", help="serve the value from the next snapshot on")
    g.add_argument("--reject", action="store_true", help="never serve the value")
    d.add_argument("--by", required=True, metavar="NAME", help="who decides (recorded with the key's name)")
    d.add_argument("--note", metavar="TEXT", help="why (recorded with the decision)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    key = os.environ.get(KEY_ENV)
    if not key:
        print(f"fooddb-review: ${KEY_ENV} is not set — it takes an API key with the `review` scope",
              file=sys.stderr)
        return 2
    base = args.url or os.environ.get(URL_ENV) or DEFAULT_URL
    if args.command == "facets":
        return _read(base, key, "/v1/review/facets", {"source": args.source, "check": args.check})
    if args.command == "queue":
        return _read(base, key, "/v1/review", {
            "source": args.source, "check": args.check, "limit": args.limit,
            "offset": args.offset, "detail": "true" if args.detail else None})
    return _decide(base, key, args)


if __name__ == "__main__":
    sys.exit(main())
