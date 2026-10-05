# fooddb

A global food database: generic nutrition and branded products by barcode, kept current and
served as a REST API, an MCP server and a CLI.

**Status: early prototype.** Fetchers for USDA FDC and Open Food Facts, async jobs on [pq](https://github.com/ricwo/pq), and a REST API.

- [docs/design.md](docs/design.md): the pipeline, the data model, sources and licences
- [docs/architecture.md](docs/architecture.md): the parts, the deployment and the data flow as built, with diagrams
- [docs/decisions.md](docs/decisions.md): what is settled, and what is still open
- [docs/landscape.md](docs/landscape.md): open-source competitors, and what we build vs reuse
- [docs/deploy.md](docs/deploy.md): self-hosting with Docker Compose: install, TLS, upgrade, backup

## Run locally

Needs Docker and [uv](https://docs.astral.sh/uv/); `./dev install` installs what is missing.

```bash
./dev up --all       # shared Postgres, this worktree's databases, API + pq worker
./dev fetch all      # queue USDA FDC (Foundation, SR Legacy) and 7 Open Food Facts deltas
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
curl "$(./dev url)/v1/foods/1?snapshot=2026-10-04"            # pinned to a day's snapshot
curl "$(./dev url)/healthz"                                   # freshness; 503 when stale
```

How data flows: fetchers write append-only observations per source record; values that fail a
check wait for review; Splink matches records into products; the nightly snapshot freezes each
product's resolved values (most trusted source per field), and the API serves that snapshot.

| Fetcher | Source | Licence | Schedule |
|---|---|---|---|
| `fdc` foundation, sr_legacy | USDA FoodData Central bulk JSON | CC0 | weekly check (USDA releases twice a year) |
| `off` | Open Food Facts daily delta files | ODbL, `off` layer | every 6 hours |
| `off-dump` | Open Food Facts full dump (~13 GB, streamed) | ODbL, `off` layer | once, then deltas |
| `match` | Splink product matching | – | after every fetch that added data |
| `snapshot` | Nightly snapshot of resolved values | – | 02:30 daily |

`uv run pytest` runs the unit tests alone; the database suite is skipped without `./dev test`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately: [SECURITY.md](SECURITY.md).

## Licence

The code is under [AGPL-3.0](LICENSE). The data is licensed separately: the core data under
fooddb's own terms, and the Open Food Facts layer under ODbL.

## Relation to eait

eait (eait.fit) is the first customer and the first data source:

- **Customer.** eait keeps a read-only local copy of the catalog (`food_ref` / `off_product`) and
  refreshes it from the nightly snapshot. It never calls this service live, so eait keeps logging
  meals when fooddb is down.
- **Data source.** When a barcode scan in eait misses or hits a stale row, eait sends the label
  photo here as an observation. No user id crosses the boundary.
