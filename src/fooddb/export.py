"""Snapshot export: one day's snapshot as NDJSON, one product per line in the REST product shape.
Consumers that keep a local copy (eait) sync from it. Streamed in batches from a server-side cursor."""

import zlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from email.utils import format_datetime

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic_core import to_json
from sqlalchemy import text

from fooddb import resolve, snapshot
from fooddb.db import engine

BATCH = 1000
NOTE = ("A day is final once it is over (UTC): its export never changes. "
        "Today's snapshot can be rebuilt until midnight UTC, so sync from a final day.")

# Every product with values that day, merges followed: a product merged after the build is exported
# once, as its survivor, with the values the snapshot froze (resolve.SNAPSHOT_SQL).
IDS_SQL = """
with recursive chain(id, merged_into) as (
    select id, merged_into from product
    where id in (select product_id from snapshot_value where day = :day and scope = :scope)
    union all
    select p.id, p.merged_into from chain c join product p on p.id = c.merged_into
)
select distinct id from chain where merged_into is null order by id
"""


def days() -> list[dict]:
    today = snapshot.today()
    with engine().connect() as conn:
        rows = conn.execute(text("select day, built_at, products from snapshot order by day desc")).mappings()
        return [dict(r, final=r["day"] < today) for r in rows]


def built_at(day: date) -> datetime | None:
    with engine().connect() as conn:
        return conn.execute(text("select built_at from snapshot where day = :d"), {"d": day}).scalar_one_or_none()


def products(day: date, include: str | None) -> Iterator[dict]:
    """Every product of the day, read in one repeatable-read transaction: a rebuild or merge mid-export is not seen."""
    scope = "all" if include == "off" else "core"
    with engine().connect() as conn:
        conn.execution_options(isolation_level="REPEATABLE READ")
        with conn.begin():
            ids = conn.execute(text(IDS_SQL), {"day": day, "scope": scope}, execution_options={"yield_per": BATCH})
            for batch in ids.scalars().partitions(BATCH):
                yield from resolve.products(list(batch), include, day, conn)


def lines(day: date, include: str | None) -> Iterator[bytes]:
    return (to_json(p) + b"\n" for p in products(day, include))


def gzipped(chunks: Iterator[bytes]) -> Iterator[bytes]:
    z = zlib.compressobj(wbits=31)
    for chunk in chunks:
        if out := z.compress(chunk):
            yield out
    yield z.flush()


router = APIRouter(prefix="/v1/snapshots", tags=["snapshots"])


@router.get("")
def list_snapshots() -> dict:
    """Snapshot days, newest first. Only a final day is safe to sync: see `note`."""
    return {"today": snapshot.today(), "note": NOTE, "items": days()}


@router.get("/{day}/export")
def export(day: date, include: str | None = None, accept_encoding: str = Header(""),
           if_none_match: str = Header("")) -> Response:
    """The whole snapshot of `day` as NDJSON. Send the ETag back in If-None-Match to skip an unchanged day."""
    built = built_at(day)
    if built is None:
        raise HTTPException(404, f"no snapshot for {day.isoformat()}")
    etag = f'W/"{day.isoformat()}.{"all" if include == "off" else "core"}.{built.timestamp():.6f}"'
    headers = {"ETag": etag, "Last-Modified": format_datetime(built.astimezone(UTC), usegmt=True),
               "Vary": "Accept-Encoding"}
    sent = {t.strip().removeprefix("W/") for t in if_none_match.split(",")}
    if "*" in sent or etag.removeprefix("W/") in sent:
        return Response(status_code=304, headers=headers)
    body = lines(day, include)
    if "gzip" in accept_encoding:
        body, headers["Content-Encoding"] = gzipped(body), "gzip"
    return StreamingResponse(body, media_type="application/x-ndjson", headers=headers)
