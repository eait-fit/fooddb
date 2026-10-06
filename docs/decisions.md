# Decisions

Technical decisions. Business decisions are tracked outside this repo.

## Settled

| Date | Decision |
|---|---|
| 2026-10-04 | fooddb is a separate repo and service, not part of the eait backend. eait consumes the nightly snapshot. |
| 2026-10-04 | Global scope. v1 covers markets where open data is rich: US, KR, JP, TW, the Nordics, DE, FR. |
| 2026-10-04 | v1 covers both generic foods and branded products. Restaurants come later. |
| 2026-10-04 | Python for everything, the API included: uv, FastAPI, SQLAlchemy with Alembic, the official MCP SDK, Typer, Splink. |
| 2026-10-04 | Open Food Facts data stays in its own attributed layer. The API returns only core data by default, and OFF data with `include=off`. Every field carries a licence tag. The OFF-derived layer is published monthly as an ODbL dump. |
| 2026-10-04 | Customers may store what they fetch. |
| 2026-10-04 | The model layer is a port with two backends: OpenRouter, and local agents (Claude, Codex, Devin) running on the user's own licence. The hosted pipeline uses OpenRouter. When customers run the CLI or MCP server locally, they can point label reads at their own key, and the results come back as observations. |
| 2026-10-04 | Data model: values per 100 g or 100 ml, plus the serving size printed on the label. |
| 2026-10-04 | Search uses `pg_trgm` only. Known limit: short CJK names match poorly. |
| 2026-10-04 | Snapshots: the API serves the latest one by default, and `?snapshot=YYYY-MM-DD` pins an earlier one for 30 days. |
| 2026-10-04 | Brand upload form in v1. The uploader's brand is checked against the GS1 company prefix. |
| 2026-10-04 | Review UI: SQLAdmin plus one custom page that shows the photo next to the fields that differ. Agents work the same queue through the API. |
| 2026-10-04 | Hosting: on eait's infrastructure, with its own Postgres database. REST is sold through RapidAPI; MCP and CLI use our own API keys. |
| 2026-10-04 | Code licence: AGPL-3.0 (changed from Apache-2.0 the same day). Anyone hosting a modified fooddb must publish their changes. API customers are not affected. The data is licensed separately: the core data under our own terms, the OFF layer under ODbL. |
| 2026-10-04 | Products are matched entities. Every source record, barcoded or not, is matched by Splink to a product id. Barcode, name, brand, language and nutrient values are features. Matches above one probability threshold (default 0.95, configurable) merge automatically, with no human step. The resolver picks per field across all sources of a product, and the licence travels with each value. |
| 2026-10-04 | Observations carry a review status. Values that pass the checks are accepted automatically; failing values stay pending and the last accepted value keeps being served. Pending values feed the review queue. |
| 2026-10-04 | Reads: values are resolved per returned product inside each query now; a nightly snapshot table is added later, and the API switches to it for speed and `?snapshot=` pinning. |
| 2026-10-04 | Data model: each value records its basis (per 100 g or per 100 ml); kJ-only energy is converted to kcal; a field that disappears from a newer source record is withdrawn; unchanged values are not stored again. |
| 2026-10-04 | Ingest streams downloads to disk and reads them line by line. A full-dump OFF fetcher bootstraps the OFF layer before the daily deltas. |
| 2026-10-05 | Snapshot pins: `?snapshot=DAY` returns the same values for the 30 days that it is kept, once that UTC day is over. Only today's snapshot is written, and a rebuild on the same day (the nightly build, or a fetcher's first data) replaces it. Thus a pin on today can change until the day ends. A merge after a build does not change a snapshot's values: a read collects the values of every product merged into the one asked for. Records and names stay live. |
| 2026-10-05 | Access: writes, the review queue and `/admin` always need an API key. Reads need one only when `FOODDB__BACKEND__REQUIRE_KEY_FOR_READS=true`. The default keeps a self-hosted read API public. Our hosted API sets it. Keys are stored as PBKDF2-HMAC-SHA256 under the server secret, so a leaked table cannot be checked against guesses without it, and a new secret retires every key. The rate limit is a per-minute window in Postgres, shared by all replicas. stdio MCP is local and needs no key. |
| 2026-10-05 | Licence tags: each served field is an object `{value, source, licence, record}`, not a flat value with a separate provenance map. Thus the tag stays with the value when a consumer copies one field, and the shape matches `per_100`. Each barcode is tagged with the most trusted record that has it. A field with no value is `null`. API version 0.3.0. |
| 2026-10-05 | Resolver rule for nutrient values, in this order: a value older than the newest candidate by more than `FOODDB__BACKEND__STALE_AFTER_DAYS` (default 730) loses. Then the value that the most distinct sources agree with wins (within 5 %, or 0.5 in the unit). Then trust rank, then the newest value. Agreement comes before rank, not only as a tie-breaker: a label read is a machine read and can be wrong, and two independent sources that agree are stronger evidence. Records of one source count as one vote, so OFF duplicates cannot outvote a table. |
| 2026-10-06 | Nutrient codes: store both carbohydrate codes and tag each value by its source. Nothing is converted between codes. `CHOCDF` (by difference, with fibre) comes from FDC nutrient 1005 and from OFF labels sold only in the US or Canada. `CHOAVL` (available, without fibre) comes from OFF labels sold only in the EU, UK, Switzerland, Norway, Iceland, Liechtenstein, Australia or New Zealand. OFF's `carbohydrates-total` is `CHOCDF`. Any other OFF label is `CHOCDF` with the flag `carbs-regime-unknown`. `ENERC_KCAL` stays the canonical energy, and `ENERC_KJ` is also kept when the source states kJ. Atwater with `CHOAVL` adds fibre at 2 kcal/g (EU 1169/2011, Annex XIV). No data migration: the stored OFF data has no market, so an old `CHOCDF` value cannot be re-coded. A delta with a newer edit of a product re-codes it and withdraws the old code. |
| 2026-10-06 | Wrong merges: every merge is logged in `merge_log`, and a reviewer can split one. A split writes a cannot-link pair between each record that moves and each record that stays. Matching never puts both records of such a pair in one product. It adds pairs to products strongest first and skips a pair that would break a constraint. Thus a cluster splits at its weakest pairs. A split product gets its old id back when the log shows that id merged away. Otherwise it gets a new id. Constraints are per record, not per product, so they survive later merges. Matching itself still never splits a product. |
| 2026-10-04 | Health means freshness: each fetcher's last successful run within its schedule, shown in `/healthz` and `./dev status`. |

## Open

1. **GS1 prefix check.** GS1's public GEPIR lookup has mostly been replaced by "Verified by GS1",
   which may require a paid GS1 membership. Find out what access costs.
2. **Legal review.** How far ODbL reaches into served answers, and whether training a model on
   OFF's CC BY-SA photos is allowed.
