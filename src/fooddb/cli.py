"""fooddb CLI: migrate, run the worker, the API and the MCP server, enqueue fetches, export a snapshot, look things up."""

import json
from pathlib import Path

import typer
from sqlalchemy import text

app = typer.Typer(no_args_is_help=True)
ROOT = Path(__file__).resolve().parents[2]


@app.command()
def migrate() -> None:
    """Apply fooddb's and pq's migrations."""
    from alembic import command
    from alembic.config import Config

    from fooddb.jobs import queue

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    queue().run_db_migrations()
    typer.echo("migrated")


@app.command()
def worker() -> None:
    """Register periodic fetches and process jobs until stopped."""
    from pq.logging import configure_logging

    from fooddb.jobs import queue, schedule

    from fooddb.db import engine

    configure_logging()
    schedule()
    # The parent forks every task: it must hold no pooled connection a child would inherit
    # (psycopg then collides on prepared statements across processes).
    engine().dispose()
    queue().run_worker(max_runtime=3600)


@app.command()
def serve(port: int = typer.Option(None, help="default: $FOODDB__BACKEND__API_PORT, else 9640"), reload: bool = False) -> None:
    """Run the REST API."""
    import os

    import uvicorn

    port = port or int(os.environ.get("FOODDB__BACKEND__API_PORT", "9640"))
    host = os.environ.get("FOODDB__BACKEND__API_HOST", "127.0.0.1")  # 0.0.0.0 inside a container
    uvicorn.run("fooddb.api:app", host=host, port=port, reload=reload, proxy_headers=True,
                forwarded_allow_ips=os.environ.get("FOODDB__BACKEND__FORWARDED_ALLOW_IPS"))


@app.command()
def mcp() -> None:
    """Run the MCP server on stdio, for a local MCP client (Claude Desktop, Claude Code)."""
    from fooddb.api import mcp as server

    server.run("stdio")


@app.command()
def enqueue(
    fetcher: str = typer.Argument(help="off | off-dump | fdc | table | match | snapshot | odbl-dump"),
    max_files: int = typer.Option(1, help="off: newest N delta files"),
    dataset: str = typer.Option("foundation", help="fdc: foundation | sr_legacy | branded"),
    source: str = typer.Option("ciqual", help="table: ciqual | fineli | matvaretabellen"),
) -> None:
    """Queue a fetch for the worker."""
    from fooddb.jobs import enqueue as _enqueue

    kwargs = {"off": {"max_files": max_files}, "fdc": {"dataset": dataset}, "table": {"source": source}}.get(fetcher, {})
    typer.echo(f"queued task {_enqueue(fetcher, **kwargs)}")


@app.command()
def run(
    job: str = typer.Argument(help="off | off-dump | fdc | table | match | snapshot | odbl-dump"),
    dataset: str = typer.Option("foundation", help="fdc: foundation | sr_legacy | branded"),
    source: str = typer.Option("ciqual", help="table: ciqual | fineli | matvaretabellen"),
) -> None:
    """Run a job in this process instead of queueing it: for loads longer than the worker's
    per-task timeout (the full OFF dump takes hours)."""
    from pq.logging import configure_logging

    from fooddb import jobs

    configure_logging()
    kwargs = {"fdc": {"dataset": dataset}, "table": {"source": source}}.get(job, {})
    {"off": jobs.fetch_off_deltas, "off-dump": jobs.fetch_off_dump, "fdc": jobs.fetch_fdc, "table": jobs.fetch_table,
     "match": jobs.match_products, "snapshot": jobs.build_snapshot, "odbl-dump": jobs.dump_odbl}[job](**kwargs)


match_app = typer.Typer(no_args_is_help=True, help="Product matching.")
app.add_typer(match_app, name="match")


@match_app.command("train")
def match_train(out: Path = typer.Option(None, help="model file; default: $FOODDB__BACKEND__MATCH_MODEL")) -> None:
    """Estimate the Splink m/u probabilities on the current records and save the model. Matching
    uses the model at $FOODDB__BACKEND__MATCH_MODEL from its next run."""
    import os

    from fooddb import match

    path = out or os.environ.get("FOODDB__BACKEND__MATCH_MODEL")
    if not path:
        typer.echo("set FOODDB__BACKEND__MATCH_MODEL or pass --out", err=True)
        raise typer.Exit(1)
    match.train(str(path))
    typer.echo(f"wrote {path}")


@app.command()
def status() -> None:
    """Row counts, recent fetch runs and queue state."""
    from fooddb.db import engine

    with engine().connect() as conn:
        for layer, n in conn.execute(text("select layer, count(*) from food group by layer order by layer")):
            typer.echo(f"foods[{layer}]: {n}")
        typer.echo(f"observations: {conn.execute(text('select count(*) from observation')).scalar_one()}")
        for r in conn.execute(text(
            "select fetcher, ref, status, foods, observations, finished_at from fetch_run order by id desc limit 5"
        )):
            typer.echo(f"run {r.fetcher} {r.ref} {r.status} foods={r.foods} obs={r.observations} {r.finished_at}")
        for r in conn.execute(text("select status, count(*) from pq_tasks group by status")):
            typer.echo(f"pq tasks {r.status}: {r.count}")


@app.command()
def export(
    day: str = typer.Option(..., help="UTC day of the snapshot, YYYY-MM-DD"),
    include_off: bool = typer.Option(False, help="add the Open Food Facts layer (ODbL)"),
    out: Path = typer.Option(..., help="NDJSON file, gzipped when the name ends in .gz"),
) -> None:
    """Write one day's snapshot as NDJSON, one product per line: the same lines as the export endpoint."""
    from datetime import date

    from fooddb import export as ex

    if ex.built_at(date.fromisoformat(day)) is None:
        typer.echo(f"no snapshot for {day}", err=True)
        raise typer.Exit(1)
    chunks = ex.lines(date.fromisoformat(day), "off" if include_off else None)
    with out.open("wb") as f:
        for chunk in ex.gzipped(chunks) if out.suffix == ".gz" else chunks:
            f.write(chunk)
    typer.echo(f"wrote {out}")


dump_app = typer.Typer(no_args_is_help=True, help="Data dumps.")
app.add_typer(dump_app, name="dump")


@dump_app.command("odbl")
def dump_odbl(out: Path = typer.Option(None, help="directory; default: $FOODDB__BACKEND__DUMP_DIR, else ./dumps")) -> None:
    """Write the ODbL dump of the Open Food Facts layer of the newest final snapshot day, with its manifest.
    Keeps the newest $FOODDB__BACKEND__DUMP_KEEP dumps (default 3) in the directory."""
    from fooddb import dump

    m = dump.write(out)
    if m is None:
        typer.echo("no final snapshot day yet", err=True)
        raise typer.Exit(1)
    typer.echo(f"wrote {m['name']}: {m['products']} products, {m['size']} bytes")


keys = typer.Typer(no_args_is_help=True, help="API keys: scopes read, review (implies read), admin (implies both).")
app.add_typer(keys, name="keys")


@keys.command("create")
def keys_create(
    name: str = typer.Option(..., help="who holds the key, e.g. eait"),
    scope: list[str] = typer.Option(["read"], help="read | review | admin; repeat for several"),
    rate_limit: int = typer.Option(None, min=1, help="requests per minute; default $FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE"),
) -> None:
    """Create a key and print its token. The token is shown only this once: only its hash is stored."""
    from fooddb import auth

    try:
        typer.echo(auth.create(name, scope, rate_limit))
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--scope")


@keys.command("list")
def keys_list() -> None:
    """Every key with its scopes, rate limit and last use. Tokens are not stored, so not shown."""
    from fooddb import auth

    for k in auth.keys():
        state = f"revoked {k['revoked_at']:%Y-%m-%d}" if k["revoked_at"] else "active"
        typer.echo(f"{k['id']}\t{k['name']}\t{','.join(k['scopes'])}\t{k['rate_limit'] or 'default'}/min\t"
                   f"{state}\tlast used {k['last_used_at'] or 'never'}")


@keys.command("revoke")
def keys_revoke(name: str) -> None:
    """Revoke the active key with this name. It stops working on the next request."""
    from fooddb import auth

    if not auth.revoke(name):
        typer.echo(f"no active key named {name}", err=True)
        raise typer.Exit(1)
    typer.echo(f"revoked {name}")


@app.command()
def lookup(barcode: str, include_off: bool = True) -> None:
    """Look up a product by barcode."""
    from fastapi import HTTPException

    from fooddb.api import by_barcode as product

    try:
        typer.echo(json.dumps(product(barcode, "off" if include_off else None), default=str, indent=2))
    except HTTPException as e:
        typer.echo(f"{barcode}: {e.detail}", err=True)
        raise typer.Exit(1)
