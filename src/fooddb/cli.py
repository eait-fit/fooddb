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
    uvicorn.run("fooddb.api:app", host=host, port=port, reload=reload, proxy_headers=True)


@app.command()
def mcp() -> None:
    """Run the MCP server on stdio, for a local MCP client (Claude Desktop, Claude Code)."""
    from fooddb.api import mcp as server

    server.run("stdio")


@app.command()
def enqueue(
    fetcher: str = typer.Argument(help="off | off-dump | fdc | match | snapshot"),
    max_files: int = typer.Option(1, help="off: newest N delta files"),
    dataset: str = typer.Option("foundation", help="fdc: foundation | sr_legacy"),
) -> None:
    """Queue a fetch for the worker."""
    from fooddb.jobs import enqueue as _enqueue

    kwargs = {"off": {"max_files": max_files}, "fdc": {"dataset": dataset}}.get(fetcher, {})
    typer.echo(f"queued task {_enqueue(fetcher, **kwargs)}")


@app.command()
def run(job: str = typer.Argument(help="off | off-dump | fdc | match | snapshot")) -> None:
    """Run a job in this process instead of queueing it: for loads longer than the worker's
    per-task timeout (the full OFF dump takes hours)."""
    from pq.logging import configure_logging

    from fooddb import jobs

    configure_logging()
    {"off": jobs.fetch_off_deltas, "off-dump": jobs.fetch_off_dump, "fdc": jobs.fetch_fdc,
     "match": jobs.match_products, "snapshot": jobs.build_snapshot}[job]()


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
