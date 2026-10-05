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

```sh
./dev install        # every tool this repo needs (uv, Docker, …)
./dev up --all       # Postgres, this worktree's databases, API + worker
./dev fetch all      # FDC and a few Open Food Facts deltas
./dev test           # unit tests + the database suite against this worktree's __test database
```

Python 3.13 or newer, through `uv`. `uv run pytest` alone skips the database suite; `./dev test`
runs it. Each git worktree gets its own ports and databases — see the README.

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
