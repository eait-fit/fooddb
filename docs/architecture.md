# Architecture

This document shows how fooddb works today: its parts, its deployment, and the flow of data from
the sources to the API. The diagrams show only code that exists. The last section,
[Planned, not built](#planned-not-built), shows what [design.md](design.md) describes but the code
does not have yet.

References have the form `file:line` and point to the code at commit `2480b2f`.

## System context

```mermaid
flowchart LR
    callers["REST and MCP callers"]
    local["Local MCP client<br/>Claude Desktop, Claude Code"]
    proxy["TLS reverse proxy<br/>Caddy"]
    subgraph fooddb["fooddb: one image, three roles"]
        api["API<br/>fooddb serve"]
        worker["Worker<br/>fooddb worker"]
        cli["CLI<br/>fooddb run, status, lookup, mcp"]
        db[("Postgres<br/>fooddb tables, pq_tasks, pq_periodic")]
    end
    fdc["USDA FoodData Central<br/>Foundation and SR Legacy bulk JSON<br/>CC0-1.0"]
    offd["Open Food Facts daily delta files<br/>ODbL-1.0"]
    offdump["Open Food Facts full dump<br/>about 13 GB jsonl.gz, ODbL-1.0"]
    callers -->|HTTPS| proxy -->|"HTTP, REST and /mcp"| api
    local -->|"stdio: fooddb mcp"| cli
    api -->|read| db
    worker -->|read, write| db
    cli -->|read, write| db
    worker -->|"HTTPS, weekly check"| fdc
    worker -->|"HTTPS, every 6 h"| offd
    cli -->|"HTTPS, manual: fooddb run off-dump"| offdump
```

fooddb has three processes, and all of them come from one image (`Dockerfile:1`):

- The **API** (`fooddb serve`, `cli.py:43`) serves REST over FastAPI. It only reads. It also serves the MCP
  server over Streamable HTTP at `/mcp`. See [MCP](#mcp).
- The **worker** (`fooddb worker`, `cli.py:26`) runs the fetches, the match job and the snapshot.
  The queue is [pq](https://github.com/ricwo/pq), which keeps its tasks in the same Postgres
  database (`jobs.py:14`).
- The **CLI** (`cli.py`) applies migrations, runs one job in the foreground, and shows the status.
  `fooddb lookup` calls the API function in its own process, not over HTTP (`cli.py:103`).
  `fooddb mcp` runs the MCP server on stdio for a local client.

The worker fetches from two upstream sources. Each value keeps the licence of its source:
`CC0-1.0` for FDC (`fetchers/fdc.py:53`) and `ODbL-1.0` for Open Food Facts (`fetchers/off.py:19`).
The worker never fetches the full OFF dump on a schedule. An operator starts it by hand
(`jobs.py:62`, [deploy.md](deploy.md#load-the-full-open-food-facts-dump)).

eait is not in this diagram. No code in fooddb or in eait reads the snapshot for eait yet. See
[Planned, not built](#planned-not-built).

## Deployment

```mermaid
flowchart TB
    client["Client"]
    subgraph host["Docker host"]
        caddy["Caddy on the host<br/>ports 80, 443<br/>(docs/deploy.md, not in Compose)"]
        subgraph stack["Compose project fooddb"]
            dbc[("db<br/>postgres:17-alpine<br/>health: pg_isready")]
            mig["migrate<br/>fooddb migrate<br/>restart: no"]
            apic["api<br/>fooddb serve, port 8000<br/>health: /livez"]
            wk["worker<br/>fooddb worker<br/>health check off"]
        end
        vol[["volume fooddb_pgdata"]]
    end
    up["fdc.nal.usda.gov<br/>static.openfoodfacts.org"]
    client -->|"HTTPS 443"| caddy
    caddy -->|"FOODDB__DEPLOY__BIND:PORT<br/>default 127.0.0.1:8000"| apic
    dbc --- vol
    mig -->|5432| dbc
    apic -->|5432| dbc
    wk -->|5432| dbc
    wk -->|HTTPS| up
    dbc ==>|service_healthy| mig
    mig ==>|service_completed_successfully| apic
    mig ==>|service_completed_successfully| wk
```

Thin arrows are network traffic. Thick arrows are the start order.

[`deploy/docker-compose.yml`](../deploy/docker-compose.yml) defines four services:

- `db` keeps its data in the `pgdata` volume (`deploy/docker-compose.yml:21`). Compose names it
  `fooddb_pgdata`, because the project name is `fooddb` (`deploy/docker-compose.yml:3`).
- `migrate` starts when `db` is healthy (`deploy/docker-compose.yml:33`). It applies the Alembic
  migrations, then the pq migrations, and stops (`cli.py:21`).
- `api` and `worker` start only after `migrate` stops with success
  (`deploy/docker-compose.yml:42`, `deploy/docker-compose.yml:49`). A failed migration keeps both
  of them down.
- Compose publishes the API port on the loopback address only (`deploy/docker-compose.yml:41`).
  A TLS reverse proxy on the host forwards to it. [deploy.md](deploy.md#tls-with-caddy) shows the
  Caddy configuration.

The image health check calls `/livez` every 30 seconds (`Dockerfile:20`). The worker turns it off
(`deploy/docker-compose.yml:48`), because the worker serves no HTTP.

### The eait production variant

eait runs the same image in its own Compose file, `deploy/docker-compose.prod.yml` in the eait
repo. It serves `https://food-api.eait.fit` since 2026-10-05. The
services are `fooddb-db`, `fooddb-migrate`, `fooddb-api` and `fooddb-worker`, with the same start
order. eait's Caddy serves `food-api.eait.fit` and forwards to `fooddb-api:8000`. `fooddb-db` is
on an internal network that only fooddb uses. `fooddb-api` is also on eait's `internal` network,
where Caddy is. `fooddb-worker` also joins the `fooddb-egress` network for its fetches.

## Data flow: from ingest to the API

```mermaid
flowchart TD
    fdcsrc["FDC zip"] -->|"stream to a tempfile, then json.load"| fdcrec["fdc.records()"]
    offsrc["OFF delta or dump, jsonl.gz"] -->|"stream, gunzip line by line"| offrec["off.records()<br/>gtin.normalize, per_100, basis"]
    fdcrec --> run["ingest.run()<br/>batches of 500 records"]
    offrec --> run
    run --> fr[("fetch_run<br/>running, done, failed")]
    run -->|"one new product per new record"| prod[("product")]
    run --> chk["checks.flags()"]
    chk --> foodt[("food<br/>one row per source record")]
    chk --> diff["_observations()<br/>changed values, withdrawn fields as null"]
    diff --> obs[("observation<br/>append-only")]
    obs -->|"status pending: the record failed a check"| queue["ingest.pending()<br/>review queue, read only"]
    obs -->|"status accepted"| match["match.run()<br/>Splink on DuckDB, in process"]
    match -->|"food.product_id, product.merged_into"| prod
    obs -->|"newest accepted value per record"| resolver["resolve.values_sql()<br/>trust rank, then newest"]
    resolver --> snap["snapshot.build()<br/>scopes core and all"]
    snap --> sv[("snapshot, snapshot_value")]
    sv --> api["API"]
    resolver -->|"only while no snapshot exists"| api
```

### Fetch

Both fetchers read their source as a stream.

- The FDC fetcher finds the newest release on the FDC download page (`fetchers/fdc.py:29`). It
  writes the zip to a tempfile, then loads the JSON file into memory (`fetchers/fdc.py:64`,
  `fetchers/fdc.py:72`). The two datasets are small, so this is acceptable.
- The OFF fetcher decompresses each `.gz` file as it arrives and yields one line at a time
  (`fetchers/off.py:111`). The file never goes to disk. A delta file and the 13 GB dump use the
  same path (`fetchers/off.py:126`).
- The delta fetcher takes every file in the OFF index that is not done yet. On the first run it
  takes only the newest file (`fetchers/off.py:132`).

### Normalise

- `gtin.normalize` stores each barcode as a GTIN-14 with a valid check digit. It rejects
  restricted-circulation and coupon prefixes: 02, 04, 05, 20–29, 98 and 99 (`gtin.py:3`). An OFF
  product without a valid global GTIN is skipped (`fetchers/off.py:94`).
- Nutrients use INFOODS tagnames: `ENERC_KCAL`, `PROCNT`, `FAT`, `CHOCDF`, `SUGAR`, `FASAT`,
  `FIBTG` and `NA` (`fetchers/off.py:22`, `fetchers/fdc.py:22`).
- Units are kcal for energy, mg for sodium and g for all other nutrients (`ingest.py:14`). The OFF
  fetcher converts kJ-only energy to kcal (`fetchers/off.py:63`).
- Each value records its basis, `100g` or `100ml` (`fetchers/off.py:76`).
- Record ids have the form `<source>:<code>`, for example `fdc:168421` or `off:<gtin14>`.

### Store observations

`ingest.run` writes one `fetch_run` row per file or release (`ingest.py:78`). It marks a run that a
killed process left in `running` as `failed` (`ingest.py:83`). A run that stores no records fails
with `EmptyRun`, because that usually means the source format changed (`ingest.py:95`).

For each batch, `_write` does these steps (`ingest.py:104`):

1. It creates one `product` row for each record that it did not see before (`ingest.py:114`).
2. It runs the checks on the record (`ingest.py:122`). The failed check names go into `food.flags`.
3. It upserts the `food` row. An older file cannot overwrite newer metadata (`ingest.py:139`).
4. It inserts observations only for values that changed, and a null value for each field that the
   source removed (`ingest.py:158`). A duplicate observation is ignored (`ingest.py:145`).

The `observation` table is append-only. The code never updates or deletes an observation.

### Checks and review status

`checks.flags` runs five checks per record (`checks.py:6`):

- Atwater energy against the macros
- protein, fat and carbohydrate over 100 g
- sugars over carbohydrate, and saturates over fat
- negative values

The checks flag values, but they do not change them.

If a record fails one check, all its new observations get the status `pending` (`ingest.py:172`).
The resolver and the match job read only `accepted` observations (`resolve.py:24`, `match.py:35`).
Thus the last accepted value stays in service. `ingest.pending()` lists the pending values
(`ingest.py:56`). No API endpoint, CLI command or UI calls it, and no code sets an observation to
`accepted` or `rejected` after the insert.

### Match records into products

`match.run` loads every record with its newest accepted energy and macros (`match.py:24`). Splink
compares only candidate pairs (`match.py:109`). A pair has the same GTIN, or the same name words at
a similar energy, or the same brand and first word at a similar energy. Clusters at or above
`FOODDB__BACKEND__MATCH_THRESHOLD` (default 0.95, `match.py:22`) merge. The lowest product id
survives. The other products get `merged_into`, and their `food` rows move to the survivor
(`match.py:158`). The match job never splits a product again.

### Resolve

The resolver picks one value per product and nutrient (`resolve.py:17`):

1. Per source record, it takes the newest accepted observation of each nutrient.
2. It drops the nulls. A withdrawn field thus falls back to the other records of the product.
3. Across records, the most trusted source wins: `brand`, then `label`, then `fdc`, then `off`
   (`resolve.py:15`). The newest value breaks a tie.

The `include=off` parameter adds the `off` layer to the query (`resolve.py:52`). Without it, OFF
values do not take part.

### Snapshot

`snapshot.build` writes the resolved values of all products for one UTC day, in one transaction
(`snapshot.py:13`). It writes two scopes: `core` (core layer only) and `all` (core and OFF). A
second build on the same day replaces that day (`snapshot.py:18`). The build deletes days that are
more than 30 days older than the new day (`snapshot.py:30`).

The API reads values from the newest snapshot, or from the day that `?snapshot=` pins
(`resolve.py:82`). Before the first snapshot exists, the API resolves values live
(`resolve.py:86`). The snapshot holds only values. Record lists, names and merges always come from
the live tables (`resolve.py:76`).

## Jobs and schedules

| Job | Function | Trigger | Priority |
|---|---|---|---|
| OFF deltas | `fetch_off_deltas` | every 6 h (`jobs.py:65`) | NORMAL |
| Snapshot | `build_snapshot` | cron `30 2 * * *`, UTC (`jobs.py:66`) | NORMAL |
| FDC Foundation, FDC SR Legacy | `fetch_fdc` | cron `0 3 * * 1`, UTC (`jobs.py:76`) | BATCH |
| Match | `match_products` | after a fetch that stored data (`jobs.py:57`) | NORMAL |
| First-boot FDC | `fetch_fdc` | once, when `fetcher_check` has no row (`jobs.py:70`) | NORMAL |
| First-boot snapshot | `build_snapshot` | once, when no snapshot exists (`jobs.py:73`) | BATCH |
| OFF full dump | `fetch_off_dump` | manual only (`cli.py:68`) | – |

pq evaluates cron in UTC (pq 0.8.1 `client.py:374`).

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker parent
    participant Q as Postgres
    participant C as Forked child
    Note over W: schedule(), jobs.py:62
    W->>Q: schedule fetch_off_deltas every 6 h, next run now
    W->>Q: schedule build_snapshot, daily 02:30 UTC
    W->>Q: read fetcher_check and snapshot (health.report)
    W->>Q: upsert bootstrap-fdc-foundation, bootstrap-fdc-sr_legacy
    W->>Q: upsert bootstrap-snapshot, priority BATCH
    W->>Q: schedule fetch_fdc for each dataset, Monday 03:00 UTC, BATCH
    Note over W: engine().dispose(), then run_worker(max_runtime=3600)
    W->>C: fork fetch_fdc foundation
    C->>Q: upsert match-products
    W->>C: fork fetch_fdc sr_legacy
    C->>Q: upsert match-products, same task
    W->>C: fork match_products
    W->>C: fork build_snapshot, the last one-off task
    Note over C: No OFF data yet. The snapshot has FDC values only.
    W->>C: fork fetch_off_deltas, now due
    C->>Q: upsert match-products
    W->>C: fork match_products
    Note over W,C: OFF products show an empty per_100 until the next snapshot.
```

The worker parent registers the schedule, then forks one child per task (`cli.py:36`). It closes
its database pool before the first fork, so that no child inherits a connection (`cli.py:39`). The
match job imports Splink and DuckDB only in the child (`jobs.py:44`). Each task has a limit of one
hour (`cli.py:40`).

The pq worker takes one task at a time. It always takes a one-off task before a periodic task, and
a higher priority first (pq 0.8.1 `worker.py:722`, `worker.py:792`). This rule sets the first-boot
order above:

1. The two FDC tasks run first. Each one queues the match task. The client id `match-products`
   collapses the two requests into one task (`jobs.py:59`).
2. The match task runs before the snapshot, because BATCH is the lowest priority.
3. The first snapshot runs next. It is the last one-off task.
4. Only then does the periodic OFF delta task run, although it was due at once.

**Known gap.** The first snapshot runs before the first OFF delta. Thus OFF products have an empty
`per_100` until the nightly snapshot at 02:30 UTC. [deploy.md](deploy.md#first-boot) tells the
operator to run `fooddb run snapshot` once after `/healthz` returns 200. The sequence in
deploy.md also leaves out the match task that runs after the FDC fetches.

Each worker start registers the OFF schedule again with the next run set to now
(pq 0.8.1 `client.py:379`). Thus a restart of the worker always checks for OFF deltas at once.

The full OFF dump takes hours, which is more than the task limit. Run it with `fooddb run off-dump`
in its own container ([deploy.md](deploy.md#load-the-full-open-food-facts-dump)). It loads a dump
only once per `Last-Modified` value of the file (`fetchers/off.py:159`).

## Database schema

```mermaid
erDiagram
    product |o--o{ product : "merged_into"
    product ||--o{ food : "product_id"
    food ||--o{ observation : "food_id"
    snapshot ||--o{ snapshot_value : "day, on delete cascade"
    product {
        bigint id PK
        bigint merged_into FK "null means canonical"
        timestamptz created_at
    }
    food {
        text id PK "source:code"
        bigint product_id FK
        text source
        text layer "core or off"
        text licence
        text gtin14 "btree index"
        text name "GIN trigram index"
        text brand
        text lang
        text serving_text
        numeric serving_g
        text_array flags "failed checks"
        timestamptz source_updated_at
        timestamptz fetched_at
    }
    observation {
        bigint id PK
        text food_id FK,UK
        text nutrient UK "INFOODS tagname"
        numeric value_per_100 "null means withdrawn"
        text unit
        text basis "100g or 100ml"
        text status "accepted, pending, rejected"
        text source UK
        text licence
        timestamptz observed_at UK
        timestamptz ingested_at
    }
    snapshot {
        date day PK
        timestamptz built_at
        int products
    }
    snapshot_value {
        date day PK,FK
        text scope PK "core or all"
        bigint product_id PK "no FK"
        text nutrient PK
        numeric value_per_100
        text unit
        text basis
        text source
        text licence
        timestamptz observed_at
    }
    fetch_run {
        bigint id PK
        text fetcher
        text ref "file or release"
        text status "running, done, failed"
        int foods
        int observations
        text error
        timestamptz started_at
        timestamptz finished_at
    }
    fetcher_check {
        text fetcher PK
        timestamptz checked_at
    }
```

Four Alembic migrations make this schema:

- `0001` enables `pg_trgm` and creates `food`, `observation` and `fetch_run`
  (`alembic/versions/0001_initial_schema.py:16`). Its `food_value` view was the first resolver.
- `0002` adds `product` and `food.product_id`. It adds `basis`, `status` and `licence` to
  `observation`, with check constraints on `status` and `basis`. It makes `value_per_100`
  nullable and drops the `food_value` view (`alembic/versions/0002_products_and_value_status.py:14`).
- `0003` adds `snapshot` and `snapshot_value` (`alembic/versions/0003_snapshots.py:14`).
- `0004` adds `fetcher_check` (`alembic/versions/0004_fetcher_check.py:14`).

The unique constraint `observation_once` covers `food_id`, `nutrient`, `source` and `observed_at`.
The index `observation_latest_idx` serves the "newest per record and nutrient" queries.
`snapshot_value.product_id` has no foreign key. `fetch_run.fetcher` and `fetcher_check.fetcher`
use the same names as the health report (`health.py:11`), but no constraint links them. pq creates
its own tables, `pq_tasks` and `pq_periodic`, through `fooddb migrate` (`cli.py:22`).

## Request flow

### `GET /v1/products/{barcode}`

```mermaid
sequenceDiagram
    autonumber
    actor Cl as Client
    participant A as api.by_barcode
    participant R as resolve.products
    participant P as Postgres
    Cl->>A: GET /v1/products/{barcode}?include=off&snapshot=2026-10-04
    A->>A: gtin.normalize(barcode)
    alt not a valid global GTIN
        A-->>Cl: 422
    end
    A->>P: product ids from food, gtin14 = code, layer in core and off
    A->>R: products(pids, include, snapshot)
    R->>P: follow product.merged_into to the survivor
    alt snapshot is given
        R->>P: does snapshot.day = 2026-10-04 exist?
        alt no
            R-->>A: NoSnapshot
            A-->>Cl: 404 no snapshot for 2026-10-04
        end
    else snapshot is not given
        R->>P: max(day) from snapshot
    end
    R->>P: records from food, always live
    alt a snapshot day is known
        R->>P: values from snapshot_value, scope all
    else no snapshot exists yet
        R->>P: resolve values live from observation
    end
    R-->>A: items
    alt no items
        A-->>Cl: 404 product not found
    else
        A-->>Cl: 200 with items
    end
```

`by_barcode` (`api.py:77`) does these steps:

1. It normalises the barcode. An invalid or non-global GTIN gets 422 (`api.py:79`).
2. It finds the products that have a record with this GTIN in the visible layers (`api.py:82`).
   Without `include=off`, only the `core` layer is visible (`resolve.py:52`).
3. `resolve.products` follows `merged_into` to the survivor product (`resolve.py:56`).
4. With `?snapshot=`, it checks that the day exists. A day that does not exist gets 404
   (`resolve.py:83`, `api.py:23`). Without `?snapshot=`, it uses the newest day.
5. It reads the records of each product from the live `food` table (`resolve.py:85`). The most
   trusted, newest record gives the name, brand and serving (`resolve.py:91`).
6. It reads the values from `snapshot_value` for the day and scope. The scope is `all` with
   `include=off`, else `core` (`resolve.py:80`). If no snapshot exists, it resolves live.
7. No visible product gets 404. Without `include=off`, the message suggests `include=off`
   (`api.py:85`).

A value in `per_100` carries its `source`, `licence`, `basis` and `observed_at`
(`resolve.py:99`). The response field `snapshot` shows the day that the values come from.

The other read endpoints use the same `resolve.products` call:

- `GET /v1/foods?q=` searches `food.name` with `pg_trgm` word similarity (`api.py:49`).
- `GET /v1/foods/{product_id}` reads one product (`api.py:64`).
- `GET /v1/records/{record_id}` finds the product of one source record (`api.py:69`).

### `/livez` and `/healthz`

```mermaid
flowchart LR
    dock["Docker health check<br/>every 30 s"] -->|"GET /livez"| lz["livez()"]
    mon["Uptime monitor"] -->|"GET /healthz"| hz["healthz()"]
    lz -->|"count products with no merged_into"| db[("Postgres")]
    lz --> l200["200 ok, products"]
    hz --> rep["health.report()"]
    rep -->|"fetcher_check, max of snapshot.built_at"| db
    rep --> dec{"each entry within<br/>its max age?"}
    dec -->|yes| h200["200"]
    dec -->|no| h503["503"]
```

- `/livez` shows that the process is up and can query the database (`api.py:34`). It says
  nothing about the age of the data. A database error gives a 500, not a 200.
- `/healthz` shows freshness (`api.py:42`). It compares each `fetcher_check` row and the newest
  `snapshot.built_at` with a maximum age (`health.py:11`): `off-delta` 12 h, `fdc-foundation` and
  `fdc-sr_legacy` 8 days, and `snapshot` 26 h. One stale entry or one entry with no row gives 503.
- A fetch that finds nothing new also counts as a successful check (`health.py:19`,
  `jobs.py:21`, `jobs.py:37`). The full OFF dump has no health entry.

### MCP

```mermaid
flowchart LR
    local["Local MCP client"] -->|"stdio: fooddb mcp"| srv["api.mcp<br/>MCPServer"]
    remote["Remote MCP client"] -->|"POST /mcp"| route["Route /mcp on the FastAPI app<br/>stateless, JSON responses"] --> srv
    srv --> tool["MCP tool<br/>include_off to include=off"]
    tool --> h["REST handler<br/>search, by_barcode, get_product, get_record"]
    tool --> rep["health.report()"]
    h --> R["resolve.products"]
    h -.->|"HTTPException"| err["tool error with the same detail"]
```

The MCP server is `mcp` in `api.py`. It uses the official MCP Python SDK (`MCPServer`). Each tool
calls the REST handler for the same read, so MCP and REST cannot answer differently:

| Tool | Calls | REST equivalent |
|---|---|---|
| `search_foods` | `search` | `GET /v1/foods?q=` |
| `get_product_by_barcode` | `by_barcode` | `GET /v1/products/{barcode}` |
| `get_food` | `get_product` | `GET /v1/foods/{product_id}` |
| `get_record_product` | `get_record` | `GET /v1/records/{record_id}` |
| `health_report` | `health.report` | `GET /healthz` |

- `include_off: true` becomes `include=off`. Without it, the tools return only the `core` layer.
  Each value keeps its `licence` tag, as in REST.
- `snapshot` pins a day, as `?snapshot=` does. `q` and `limit` have the same limits as REST.
- A 404 or 422 from the handler becomes an MCP tool error with the same message.
- Over HTTP, the FastAPI lifespan runs the SDK's session manager. The route is stateless, so any
  API replica can answer any request.
- When `FOODDB__BACKEND__API_HOST` is `127.0.0.1` (the local default), the SDK refuses requests
  with a `Host` header other than localhost. In the image the value is `0.0.0.0`, so the check is
  off, and the reverse proxy sets the host.
- The MCP server has no authentication, like the REST API.

## Planned, not built

[design.md](design.md) and [decisions.md](decisions.md) describe these parts. The code does not
have them yet. Dashed boxes and dashed arrows are planned. Solid boxes exist today.

```mermaid
flowchart LR
    subgraph built["As built"]
        api["REST API"]
        obs[("observation")]
        pend["pending observations"]
        snap[("snapshot_value")]
    end
    tables["Other composition tables<br/>CIQUAL, BLS, Fineli, MFDS, MEXT"]
    brand["Brand upload form<br/>GS1 prefix check"]
    eaitp["eait label photos<br/>no user id"]
    port["Model port"]
    orouter["OpenRouter"]
    agents["Local agents<br/>Claude, Codex, Devin"]
    review["Review UI<br/>SQLAdmin and photo page"]
    keys["API keys, rate limits<br/>RapidAPI listing"]
    eaitc["eait local copy<br/>food_ref, off_product"]
    odbl["Monthly ODbL dump<br/>of the off layer"]
    tables -.->|"source rows"| obs
    brand -.->|"source brand"| obs
    eaitp -.-> port
    port -.-> orouter
    port -.-> agents
    port -.->|"source label"| obs
    pend -.-> review
    review -.->|"accept or reject"| obs
    keys -.-> api
    snap -.->|"nightly refresh"| eaitc
    obs -.-> odbl
    classDef planned stroke-dasharray: 5 5
    class tables,brand,eaitp,port,orouter,agents,review,keys,eaitc,odbl planned
```

- **Intake.** Other national composition tables, the brand upload form with its GS1 prefix
  check, and label reads from eait photos. The resolver already ranks the sources `brand` and
  `label` above `fdc` (`resolve.py:15`), but no fetcher writes them.
- **Model port.** One port for all LLM work, with OpenRouter for the hosted pipeline and local
  agents for customers' own runs.
- **Review.** A review UI on SQLAdmin, plus a page that shows the photo next to the fields that
  differ. Agents use the same queue through the API. Today no code changes the status of a pending
  observation.
- **Checks.** Ranges per category, and front-of-pack warning seals.
- **Access.** API keys, rate limits and the RapidAPI listing. The REST API and the MCP server have
  no authentication today.
- **eait as a consumer.** eait keeps a read-only local copy and refreshes it from the nightly
  snapshot. No export endpoint or eait job exists yet.
- **ODbL dump.** A monthly ODbL dump of the OFF-derived layer.
