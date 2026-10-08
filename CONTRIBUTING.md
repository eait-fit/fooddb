# Contributing

Thanks for looking. fooddb is a global food database: fetchers for open nutrition sources, product
matching, and a REST API over the result. [eait.fit](https://eait.fit) is its first customer, but
nothing here is specific to it.

## Before you write code

- **Read [`docs/design.md`](docs/design.md) and [`docs/decisions.md`](docs/decisions.md).** The
  decisions table is what is settled. A PR that reverses a settled decision without an issue that
  argues for it is refused however green it is.
- **Open an issue first for anything beyond a small fix.** One ticket, one branch, one PR. A defect
  you notice on the way is a new issue, not another commit.
- **Data licences travel with the data.** Every value carries a licence tag, and Open Food Facts
  data stays in its own `off` layer. A new source names its licence before its fetcher is written.

## Setting up

Needs Docker and [uv](https://docs.astral.sh/uv/). `./dev install` installs what is missing.

```sh
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

Try the API of your worktree:

```sh
curl "$(./dev url)/v1/foods?q=hummus"                         # search products
curl "$(./dev url)/v1/products/06297001181102?include=off"    # by barcode, with the OFF layer
curl "$(./dev url)/v1/records/fdc:168421"                     # the product a source record belongs to
curl "$(./dev url)/v1/foods/1?snapshot=2026-10-04"            # pinned to a day's snapshot
curl "$(./dev url)/healthz"                                   # freshness; 503 when stale
KEY=$(./dev cli keys create --name me --scope review)         # printed once; only its hash is stored
curl -H "Authorization: Bearer $KEY" "$(./dev url)/v1/review" # values a failed check held back
```

API keys and `/admin` need `FOODDB__BACKEND__SECRET_KEY`. The commands that
[docs/usage.md](docs/usage.md) shows with `fooddb` run in a checkout as `./dev cli …`.

Python 3.13 or newer, through `uv`. `uv run pytest` alone runs the unit tests and skips the
database suite. `./dev test` runs both.

## Writing the change

- **Test first** at the agreed seams: the HTTP API, the fetcher parsers, the ingest write path and
  the dev environment. The failing test first, then the code.
- **One logical change per commit**, with a message that says what holds now and why.
- **Matching never splits a product.** Changes to Splink settings or blocking come with cases in
  `tests/test_db.py` that show the merges still hold.
- **The worker forks every task.** Never import Splink, DuckDB or pyarrow in the worker parent, and
  never let the parent keep pooled database connections before it forks.
- **A new configuration value** is `FOODDB__BACKEND__<KEY>`, read with a default where it has one,
  and a line in `.env.example` (or `deploy/.env.example` for the self-hosted stack).

## Opening the PR

- `./dev test` green, and the PR says so with the numbers, not "tests pass".
- The body is what it does and what proves it, in that order, and links the issue.
- CI runs the same suite against Postgres, builds the image, and scans for leaked secrets.
- Merge is squash. Review fixes go on the same branch; an out-of-scope finding is a ticket.

## Security

Do not open an issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the AGPL-3.0, like the rest of
this repository's code.
