"""REST API over products. Core data by default; the ODbL "off" layer only with include=off."""

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from fooddb import gtin, health, resolve
from fooddb.db import engine

app = FastAPI(title="fooddb", version="0.2.0")


def _pids(sql: str, **params) -> list[int]:
    with engine().connect() as conn:
        return list(conn.execute(text(sql), params).scalars())


def _resolve(pids: list[int], include: str | None, snapshot: date | None) -> list[dict]:
    try:
        return resolve.products(pids, include, snapshot)
    except resolve.NoSnapshot as e:
        raise HTTPException(404, str(e))


def _one(pids: list[int], include: str | None, what: str, snapshot: date | None = None) -> dict:
    found = _resolve(pids, include, snapshot)
    if not found:
        raise HTTPException(404, f"{what} not found" + ("" if include == "off" else " in core; try include=off"))
    return found[0]


@app.get("/livez")
def livez() -> dict:
    """The process is up and reaches the database. Says nothing about data freshness."""
    with engine().connect() as conn:
        n = conn.execute(text("select count(*) from product where merged_into is null")).scalar_one()
    return {"ok": True, "products": n}


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Freshness: 503 when any fetcher or the snapshot is older than its schedule allows."""
    r = health.report()
    return JSONResponse(r, status_code=200 if r["ok"] else 503)


@app.get("/v1/foods")
def search(q: str = Query(min_length=2), include: str | None = None, limit: int = Query(20, ge=1, le=100),
           snapshot: date | None = None) -> dict:
    # Word similarity: a short query against a long name ("beans" in "Beans, snap, green, raw").
    pids = _pids(
        """select product_id from food
           where layer = any(:layers) and :q <% name
           group by product_id
           order by max(word_similarity(:q, name)) desc, min(length(name))
           limit :limit""",
        q=q, layers=resolve.layers_for(include), limit=limit,
    )
    return {"items": _resolve(pids, include, snapshot)}


@app.get("/v1/foods/{product_id}")
def get_product(product_id: int, include: str | None = None, snapshot: date | None = None) -> dict:
    return _one([product_id], include, "product", snapshot)


@app.get("/v1/records/{record_id}")
def get_record(record_id: str, include: str | None = None, snapshot: date | None = None) -> dict:
    """The product a source record (e.g. "fdc:174289", "off:0…") belongs to."""
    pids = _pids("select product_id from food where id = :id and layer = any(:layers)",
                 id=record_id, layers=resolve.layers_for(include))
    return _one(pids, include, "record", snapshot)


@app.get("/v1/products/{barcode}")
def by_barcode(barcode: str, include: str | None = None, snapshot: date | None = None) -> dict:
    code = gtin.normalize(barcode)
    if code is None:
        raise HTTPException(422, "not a valid global GTIN")
    pids = _pids("select distinct product_id from food where gtin14 = :code and layer = any(:layers)",
                 code=code, layers=resolve.layers_for(include))
    items = _resolve(pids, include, snapshot)
    if not items:
        raise HTTPException(404, "product not found" + ("" if include == "off" else " in core; try include=off"))
    return {"items": items}
