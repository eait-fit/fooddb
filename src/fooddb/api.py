"""REST API and MCP server over products. Core data by default; the ODbL "off" layer only with
include=off (include_off in MCP)."""

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from fooddb import admin, auth, export, gtin, health, resolve, review
from fooddb.db import engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="fooddb", version="0.3.0", lifespan=lifespan)
READ = [auth.require("read")]
app.include_router(export.router, dependencies=READ)


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


@app.get("/v1/foods", dependencies=READ)
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


@app.get("/v1/foods/{product_id}", dependencies=READ)
def get_product(product_id: int, include: str | None = None, snapshot: date | None = None) -> dict:
    return _one([product_id], include, "product", snapshot)


@app.get("/v1/records/{record_id}", dependencies=READ)
def get_record(record_id: str, include: str | None = None, snapshot: date | None = None) -> dict:
    """The product a source record (e.g. "fdc:174289", "off:0…") belongs to."""
    pids = _pids("select product_id from food where id = :id and layer = any(:layers)",
                 id=record_id, layers=resolve.layers_for(include))
    return _one(pids, include, "record", snapshot)


@app.get("/v1/products/{barcode}", dependencies=READ)
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


# Review: the only writes.
review_router = APIRouter(prefix="/v1/review", tags=["review"], dependencies=[auth.require("review")])


class Decision(BaseModel):
    decision: Literal["accept", "reject"]
    by: str = Field(min_length=1, description="who decided")
    note: str | None = None


@review_router.get("")
def review_queue(limit: int = Query(100, ge=1, le=1000)) -> dict:
    """Values a failed check held back, grouped per source record, next to the values served now."""
    return {"items": review.queue(limit)}


@review_router.post("/{observation_id}")
def decide_review(observation_id: int, body: Decision) -> dict:
    """Accept a pending value (served from the next snapshot on) or reject it (never served)."""
    try:
        return review.decide(observation_id, body.decision, body.by, body.note)
    except review.NotPending as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


app.include_router(review_router)
admin.mount(app)


mcp = MCPServer("fooddb", instructions="Food nutrition per 100 g or 100 ml. Every field carries its source and licence. "
                "Core data by default; include_off=True adds the Open Food Facts layer (ODbL).")


def _tool(handler, *args, **kwargs) -> dict:
    """An MCP tool answers with the REST handler's body, and its HTTP error as a tool error."""
    try:
        return handler(*args, **kwargs)
    except HTTPException as e:
        raise ToolError(e.detail)


def _needs(ctx: Context, scope: str) -> None:
    """Over HTTP, the caller the /mcp route authenticated must hold the scope. stdio is local and trusted."""
    request = ctx.request_context.request
    if request is None:
        return
    caller = request.scope.get("state", {}).get("caller")
    if caller is None or scope not in caller.scopes:
        raise ToolError(f"this tool needs an API key with the {scope} scope")


def _include(include_off: bool) -> str | None:
    return "off" if include_off else None


@mcp.tool()
def search_foods(q: Annotated[str, Field(min_length=2)], limit: Annotated[int, Field(ge=1, le=100)] = 20,
                 snapshot: date | None = None, include_off: bool = False) -> dict[str, Any]:
    """Search foods and products by name."""
    return _tool(search, q=q, include=_include(include_off), limit=limit, snapshot=snapshot)


@mcp.tool()
def get_product_by_barcode(barcode: str, snapshot: date | None = None,
                           include_off: bool = False) -> dict[str, Any]:
    """Products with this barcode (GTIN-8, -12, -13 or -14)."""
    return _tool(by_barcode, barcode, _include(include_off), snapshot)


@mcp.tool()
def get_food(product_id: int, snapshot: date | None = None, include_off: bool = False) -> dict[str, Any]:
    """One product by its fooddb id."""
    return _tool(get_product, product_id, _include(include_off), snapshot)


@mcp.tool()
def get_record_product(record_id: str, snapshot: date | None = None,
                       include_off: bool = False) -> dict[str, Any]:
    """The product a source record (e.g. "fdc:174289", "off:0…") belongs to."""
    return _tool(get_record, record_id, _include(include_off), snapshot)


@mcp.tool()
def health_report() -> dict[str, Any]:
    """Data freshness: each fetcher's last successful check and the snapshot age, against its schedule."""
    return health.report()


@mcp.tool(name="review_queue")
def review_queue_tool(ctx: Context, limit: Annotated[int, Field(ge=1, le=1000)] = 100) -> dict[str, Any]:
    """Values a failed check held back, grouped per source record, next to the values served now."""
    _needs(ctx, "review")
    return _tool(review_queue, limit)


@mcp.tool(name="decide_review")
def decide_review_tool(ctx: Context, observation_id: int, decision: Literal["accept", "reject"], by: str,
                       note: str | None = None) -> dict[str, Any]:
    """Accept a pending value (served from the next snapshot on) or reject it (never served). `by` names who decided."""
    _needs(ctx, "review")
    return _tool(decide_review, observation_id, Decision(decision=decision, by=by, note=note))


class _Authenticated:
    """Every /mcp request needs what a REST read needs. The caller rides in the ASGI state for _needs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            caller = await run_in_threadpool(auth.check, Request(scope), "read")
        except HTTPException as e:
            return await JSONResponse({"detail": e.detail}, e.status_code, e.headers)(scope, receive, send)
        scope.setdefault("state", {})["caller"] = caller
        await self.app(scope, receive, send)


# Streamable HTTP at /mcp, served by this app. Stateless, so any API replica answers any request.
[_mcp_route] = mcp.streamable_http_app(
    stateless_http=True, json_response=True, host=os.environ.get("FOODDB__BACKEND__API_HOST", "127.0.0.1"),
).routes
app.router.routes.append(Route(_mcp_route.path, _Authenticated(_mcp_route.endpoint)))
