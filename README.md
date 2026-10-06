# fooddb

A global food database: generic nutrition and branded products by barcode, kept current and
served as a REST API, an MCP server and a CLI.

**Status: early prototype.** Fetchers for USDA FDC, CIQUAL, CoFID, Fineli, Matvaretabellen and Open Food Facts, async jobs on [pq](https://github.com/ricwo/pq), a REST API and an MCP server.

- [docs/design.md](docs/design.md): the pipeline, the data model, sources and licences
- [docs/architecture.md](docs/architecture.md): the parts, the deployment and the data flow as built, with diagrams
- [docs/decisions.md](docs/decisions.md): what is settled, and what is still open
- [docs/landscape.md](docs/landscape.md): open-source competitors, and what we build vs reuse
- [docs/deploy.md](docs/deploy.md): self-hosting with Docker Compose: install, TLS, upgrade, backup
- [docs/data-licence.md](docs/data-licence.md): the data licences, the ODbL attribution and its share-alike obligation

## Run locally

Needs Docker and [uv](https://docs.astral.sh/uv/); `./dev install` installs what is missing.

```bash
./dev up --all       # shared Postgres, this worktree's databases, API + pq worker
./dev fetch all      # queue USDA FDC (Foundation, SR Legacy), CIQUAL, Matvaretabellen and 7 OFF deltas
./dev jobs           # row counts, fetch runs, queue state
./dev status         # this worktree;  ./dev ls  for every worktree
./dev test           # unit tests + the database suite against this worktree's __test database
./dev down
```

`./dev` with no arguments lists every command. Each git worktree gets its own slot: the API port
(9640 + 10 × slot) and its own dev and `__test` databases on one shared Postgres (port 5440). All
of these are derived into `.env.worktree` by `scripts/dev_env.py`.

```bash
curl "$(./dev url)/v1/foods?q=hummus"                         # search products
curl "$(./dev url)/v1/products/06297001181102?include=off"    # by barcode, with the OFF layer
curl "$(./dev url)/v1/records/fdc:168421"                     # the product a source record belongs to
curl "$(./dev url)/v1/foods/1?snapshot=2026-10-04"            # pinned to a day's snapshot (see below)
curl "$(./dev url)/healthz"                                   # freshness; 503 when stale
KEY=$(./dev cli keys create --name me --scope review)          # printed once; only its hash is stored
curl -H "Authorization: Bearer $KEY" "$(./dev url)/v1/review"  # values a failed check held back
curl -X POST "$(./dev url)/v1/review/42" -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"decision": "reject", "by": "kirill", "note": "10x typo"}'
```

Every served field carries its `source`, its `licence` and the source `record` it comes from. A
product from `/v1/records/fdc:9?include=off`, shortened:

```json
{
  "id": 1,
  "records": ["fdc:9", "off:04006381333931"],
  "gtin14": [{"value": "04006381333931", "source": "fdc", "licence": "CC0-1.0", "record": "fdc:9"}],
  "snapshot": "2026-10-04",
  "name": {"value": "ACME, HUMMUS CLASSIC", "source": "fdc", "licence": "CC0-1.0", "record": "fdc:9"},
  "brand": {"value": "Acme", "source": "fdc", "licence": "CC0-1.0", "record": "fdc:9"},
  "lang": null,
  "serving_text": null,
  "serving_g": null,
  "category": {"value": "legumes", "source": "fdc", "licence": "CC0-1.0", "record": "fdc:9"},
  "flags": {"value": [], "source": "fdc", "licence": "CC0-1.0", "record": "fdc:9"},
  "per_100": {
    "ENERC_KCAL": {"value": 229.0, "unit": "kcal", "basis": "100g", "source": "fdc",
                   "licence": "CC0-1.0", "observed_at": "2026-01-01T00:00:00Z"},
    "FIBTG": {"value": 6.0, "unit": "g", "basis": "100g", "source": "off",
              "licence": "ODbL-1.0", "observed_at": "2026-01-01T00:00:00Z"}
  },
  "seals": {"value": {"CL": {"calories": false}, "MX": {"calories": false}},
            "source": "fooddb", "licence": "CC0-1.0", "record": null},
  "attribution": []
}
```

Nutrients in `per_100` use INFOODS codes: `ENERC_KCAL` (kcal), `ENERC_KJ` (kJ, when the source
states it), `PROCNT`, `FAT`, `CHOCDF`, `CHOAVL`, `SUGAR`, `FASAT`, `FIBTG` (g) and `NA` (mg). The two
carbohydrate codes are different quantities, and a product can have both. `CHOCDF` is
carbohydrate by difference, with fibre: USDA FDC and US or Canadian labels. `CHOAVL` is available
carbohydrate, without fibre: EU, UK, Australian and similar labels. fooddb never converts one into
the other. An Open Food Facts value whose label market is unknown is `CHOCDF`, and the record has
the flag `carbs-regime-unknown`.

`seals` are the front-of-pack warning seals of Chile (`CL`), Mexico (`MX`) and Peru (`PE`) that
the served values imply, computed on each read. A seal whose inputs are missing is left out. The
schemes count added sugars, fats and sodium, and fooddb has total values, so a seal is an upper
bound on the label. Its licence is the most restrictive among the values it reads.

`attribution` lists the text that each source of a served field asks you to show: CIQUAL, CoFID,
Fineli and Matvaretabellen. See [docs/data-licence.md](docs/data-licence.md).

A field is `null` when the record that names the product has no value for it. Without
`include=off`, the same product has only `fdc:9`, and no field in it comes from Open Food Facts.

The review queue is also in a browser at `$(./dev url)/admin`. Log in with an `admin` key in the
password field. API keys and `/admin` need `FOODDB__BACKEND__SECRET_KEY`: it keys the stored key hashes and signs the
admin login cookie.

The same login opens four more pages: **Overview** (counts per source and layer, snapshot, dump,
credits), **Jobs** (the pq queue with errors, schedules, fetch runs, freshness, and **Run now**
buttons), **Requests** (the request log: per hour or day, by status, key and route, p50 and p95)
and **Users** (accounts, credits, keys; grant credits, set unlimited, revoke a key). Each action is a
POST form with a CSRF token. The request log keeps the route template, never the URL or query,
and `FOODDB__BACKEND__REQUEST_LOG_DAYS` (default 30) sets how long.

## Authentication

API keys look like `fdb_…`. Send one as `Authorization: Bearer fdb_…` or `X-API-Key: fdb_…`.
`fooddb keys create --name NAME --scope read|contribute|review|admin` makes one and prints it once.
`fooddb keys list` and `fooddb keys revoke NAME` manage them.

- `read`: the data routes, the snapshot export and the MCP read tools.
- `contribute`: `read`, plus label photos at `/v1/labels`.
- `review`: `contribute`, plus `/v1/review` and the MCP review tools.
- `admin`: `review`, plus the login to `/admin`.

Writes, the review queue and `/admin` always need a key. Reads need a key only when
`FOODDB__BACKEND__REQUIRE_KEY_FOR_READS=true`. The default is `false`, so a self-hosted read API
stays public. `/livez` and `/healthz` are always open. Each key has a rate limit per minute
(`FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE`, default 60, or `--rate-limit`). Reads without a key have
the same limit per client IP. Over the limit, the API answers 429 with `Retry-After`. Behind
RapidAPI, a request with the listing's `X-RapidAPI-Proxy-Secret`
(`FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET`) counts as a `read` key.

## Get an API key

On a hosted fooddb, open `/portal` (for example `https://food-api.eait.fit/portal`), enter your email
and open the link that arrives. There you create read keys, see your credits and this month's
requests, and buy a pack: 100,000 requests for EUR 29.99, paid once through Stripe, with no
expiry and no free tier. Each read with your key costs one credit. At zero the API answers 402 with a
link to the portal. A self-hosted setup can leave the portal off: it needs the Stripe and Resend
settings in [docs/deploy.md](docs/deploy.md#selling-access).

## MCP

The MCP server has the same reads as the REST API, and calls the same functions. Its tools are
`search_foods`, `get_product_by_barcode`, `get_food`, `get_record_product` and `health_report`,
plus the review tools `review_queue` and `decide_review`, and `read_label` on stdio.
Each field carries its licence tag, as in REST. OFF data comes back only with `include_off: true`.

Two transports:

- **stdio**, for a local client: `fooddb mcp`. It needs `FOODDB__BACKEND__DATABASE_URL`. It is
  local and trusted, so it needs no API key.
- **Streamable HTTP** at `/mcp` on the API: `$(./dev url)/mcp` locally, `https://<your host>/mcp`
  when self-hosted. Send an API key in the `Authorization` header, as for REST. The read tools
  need what a REST read needs. `review_queue` and `decide_review` need the `review` scope.

Claude Code:

```bash
claude mcp add fooddb --env FOODDB__BACKEND__DATABASE_URL=postgresql://… -- uv run --directory /path/to/fooddb fooddb mcp
claude mcp add --transport http fooddb "$(./dev url)/mcp" --header "Authorization: Bearer fdb_…"   # or over HTTP
```

Claude Desktop, in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fooddb": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fooddb", "fooddb", "mcp"],
      "env": {"FOODDB__BACKEND__DATABASE_URL": "postgresql://…"}
    }
  }
}
```

How data flows: fetchers write append-only observations per source record; values that fail a
check wait for review; Splink matches records into products; the nightly snapshot freezes each
product's resolved values (most trusted source per field), and the API serves that snapshot.

`?snapshot=YYYY-MM-DD` pins the values of one UTC day's snapshot for 30 days. A day is final when
it is over: a pin on an earlier day always returns the same values. Today's snapshot can be rebuilt
until midnight UTC, so a pin on today can change. A product that matching merged after the build
keeps the values the snapshot froze, and a merged-away product id answers as its survivor. Record
lists and names are always live.

## Read a label with your own Claude or Codex subscription

The MCP tool `read_label` reads a nutrition label photo into per-100 values on your machine. It
runs `claude -p` (Claude Code) or `codex exec` (Codex CLI) as a subprocess, so your own
subscription pays for the read. It works only over stdio (`fooddb mcp`), needs no API key, and
sends nothing to a fooddb server unless you ask it to.

1. Install Claude Code or Codex CLI, and log in once.
2. Add the server: `claude mcp add fooddb -- uv run --directory /path/to/fooddb fooddb mcp`.
   No database is necessary for `read_label`.
3. Give the client a photo. The tool takes the photo as base64 (JPEG, PNG or WebP, at most
   10 MiB), plus an optional `barcode` and `name`. `reader` is `claude-cli` (default),
   `codex-cli`, `openrouter` (with your own `FOODDB__BACKEND__LLM_API_KEY`) or `demo`. Set
   `FOODDB__BACKEND__LABEL_READER` to change the default.
4. To contribute the read, call the tool with `submit: true`. It posts the photo and the read to
   `FOODDB__BACKEND__SUBMIT_URL` with the `contribute` key in `FOODDB__BACKEND__SUBMIT_KEY`. The
   server does not read the photo again. Every value waits for review there.

A server reads photos itself through `POST /v1/labels`:

```bash
curl -H "Authorization: Bearer $KEY" -F photo=@label.jpg -F barcode=4006381333931 "$(./dev url)/v1/labels"
# {"task": 17, "photo": "9f2c…", "record": "label:9f2c…"}
curl -H "Authorization: Bearer $KEY" "$(./dev url)/v1/labels/17"   # pending, running, completed or failed
```

The worker reads the photo with OpenRouter (`FOODDB__BACKEND__LLM_API_KEY`, model
`FOODDB__BACKEND__LLM_MODEL`). Without a key, it uses the demo reader. The values become the
source record `label:<sha256>`. The checks run as for every source. A read below
`FOODDB__BACKEND__LABEL_CONFIDENCE_FLOOR` (default 0.9) waits for review in full. Reviewers see the
photo next to the values on the **Label reads** page in `/admin`.

## Brand uploads

A brand sends its own values with a label photo. The upload needs a key with the `contribute`
scope. Use the form at `/brands/upload` (paste the key in the password field), or post it:

```bash
curl -H "Authorization: Bearer $KEY" "$(./dev url)/v1/brands/uploads" \
  -F photo=@label.jpg -F barcode=4006381333931 -F name="Acme Hummus" -F brand=Acme \
  -F basis=100g -F ENERC_KCAL=229 -F PROCNT=7.4 -F FAT=17.1 -F serving_g=30
```

The fields are `barcode`, `name`, `brand`, `basis`, one field for each INFOODS code (`ENERC_KCAL`,
`ENERC_KJ`, `PROCNT`, `FAT`, `CHOCDF`, `CHOAVL`, `SUGAR`, `FASAT`, `FIBTG`, `NA`), `serving_text`,
`serving_g` and `photo`. The values become the source record `brand:<gtin14>`. The GS1 check
(`FOODDB__BACKEND__GS1_VERIFIER`) has only the backend `none`. Thus every value waits for review,
and nothing from the upload is served until a reviewer accepts a value. Reviewers see the photo next
to the values on the **Label reads** page in `/admin`.

## Fix a wrong merge

Matching merges products above the match threshold with no human step, and logs each merge. To
undo a wrong merge, split the records out of the product:

```bash
curl -X POST "$(./dev url)/v1/products/1234/split" -H 'content-type: application/json' \
  -d '{"food_ids": ["off:04006381333931"], "by": "kirill", "note": "two different recipes"}'
```

The records go back to the product id they had before the merge, so old links to that id work
again. When the log has no such id, they get a new product. Matching never joins the moved records
and the remaining records again. Past snapshot days keep their values; today's values change at the
next snapshot build. Agents call the MCP tool `split_product`. In SQLAdmin, open **Merge log** at
`/admin`, select the merge and run **Split**.

`./dev cli match train` estimates the Splink weights on the current data and saves the model to
`FOODDB__BACKEND__MATCH_MODEL`. Matching uses that model from its next run. Without it, matching
uses the hand-set weights.

## Sync a local copy

A consumer that keeps its own copy of the catalog (eait does) syncs from the snapshot export. It
does not call the per-product endpoints. Customers may store what they fetch.

1. **List the days.** `GET /v1/snapshots` returns each day, newest first, with `built_at`, a
   product count and `final`. A day is final when it is over (UTC). Today's snapshot can still be
   rebuilt, so sync only from a day where `final` is `true`.
2. **Export the day.** `GET /v1/snapshots/{day}/export` returns NDJSON: one product per line, in
   the same shape as `GET /v1/foods/{id}?snapshot={day}`, with a licence tag on each field. The
   OFF layer (ODbL) is in the export only with `include=off`. Send `Accept-Encoding: gzip` for a
   gzipped body.
3. **Skip an unchanged day.** Keep the `ETag`. Send it back in `If-None-Match`, and the API
   answers `304 Not Modified` with no body. A final day's ETag never changes.
4. **Load it.** Replace the local copy with the lines of the new day in one transaction. A
   product that is not in the export is not in that snapshot any more: it was merged into another
   product, or it has no values.

```bash
curl "$(./dev url)/v1/snapshots"
curl -H 'Accept-Encoding: gzip' -o 2026-10-04.ndjson.gz "$(./dev url)/v1/snapshots/2026-10-04/export?include=off"
./dev cli export --day 2026-10-04 --include-off --out 2026-10-04.ndjson.gz   # the same lines, from the database
```

The export is a read: it needs a `read` key when `FOODDB__BACKEND__REQUIRE_KEY_FOR_READS=true`.

## ODbL dump of the Open Food Facts layer

Each month fooddb publishes the Open Food Facts part of its data as an ODbL dump. A line is one
product with an OFF record: its fooddb id, its `off:` record ids, and only the fields and values
tagged `ODbL-1.0`. The dumps need no API key, also when reads need one. They count against the
rate limit.

```bash
curl "$(./dev url)/v1/dumps"                                    # manifests: day, products, size, sha256, licence
curl -OJ "$(./dev url)/v1/dumps/fooddb-off-odbl-2026-09-30.ndjson.gz"
./dev cli dump odbl --out dumps/                                # write one now, from the newest final day
```

The worker writes a dump on the 1st of each month at 04:00 UTC and keeps the newest 3. Use of the
dump comes with the ODbL attribution and share-alike obligation: see
[docs/data-licence.md](docs/data-licence.md).

| Fetcher | Source | Licence | Schedule |
|---|---|---|---|
| `fdc` foundation, sr_legacy | USDA FoodData Central bulk JSON | CC0 | weekly check (USDA releases twice a year) |
| `fdc` branded | USDA FoodData Central Branded Foods (~3 GB JSON, streamed) | CC0 | weekly check, only with `FOODDB__BACKEND__FETCH_FDC_BRANDED=true` |
| `table` ciqual | CIQUAL, French food composition table (ANSES), Excel | Etalab 2.0, attribution | weekly check |
| `table` cofid | CoFID, UK composition of foods integrated dataset (Public Health England), Excel | OGL v3.0, attribution | weekly check |
| `table` fineli | Fineli, Finnish food composition database (THL), zip of CSV | CC BY 4.0, attribution | weekly check, only with `FOODDB__BACKEND__FETCH_FINELI=true` |
| `table` matvaretabellen | Matvaretabellen, Norwegian food composition table, JSON API | NLOD 2.0, attribution | weekly check |
| `off` | Open Food Facts daily delta files | ODbL, `off` layer | every 6 hours |
| `off-dump` | Open Food Facts full dump (~13 GB, streamed) | ODbL, `off` layer | manual (`fooddb run off-dump`), deltas keep it current |
| `match` | Splink product matching | – | after every fetch that added data |
| `snapshot` | Nightly snapshot of resolved values | – | 02:30 daily |
| `odbl-dump` | ODbL dump of the OFF layer, newest final day | ODbL | 04:00 on the 1st of each month |

`uv run pytest` runs the unit tests alone; the database suite is skipped without `./dev test`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately: [SECURITY.md](SECURITY.md).

## Licence

The code is under [AGPL-3.0](LICENSE). The data is licensed separately: the core data under
fooddb's own terms, and the Open Food Facts layer under ODbL. See
[docs/data-licence.md](docs/data-licence.md) for the attribution and the share-alike obligation.

## Relation to eait

eait (eait.fit) is the first customer and the first data source:

- **Customer.** eait keeps a read-only local copy of the catalog (`food_ref` / `off_product`) and
  refreshes it from the nightly snapshot. It never calls this service live, so eait keeps logging
  meals when fooddb is down.
- **Data source.** When a barcode scan in eait misses or hits a stale row, eait is to send the
  label photo to `POST /v1/labels` with a `contribute` key. No user id crosses the boundary. The
  fooddb side is built. eait does not send photos yet.
