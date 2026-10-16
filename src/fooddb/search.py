"""Finding products: by name, by source record, by barcode. Each returns the products in answer order,
as `resolve.products` serves them; what a miss means is the caller's (the API's 404, the CLI's exit 1)."""

from sqlalchemy import ColumnElement, Select, case, false, func, literal, literal_column, select, union_all

from fooddb import countries, resolve
from fooddb.db import engine, food, food_name, observation

CANDIDATES = 20  # name rows ranked per result row before the visibility check


def _pids(stmt: Select) -> list[int]:
    with engine().connect() as conn:
        return list(conn.execute(stmt).scalars())


def _visible() -> ColumnElement[bool]:
    """A record shows when no value of it is accepted-less: some accepted value, or none at all (resolve.VISIBLE)."""
    o = observation.alias("o")
    return select(func.bool_or(o.c.status == "accepted")).where(o.c.food_id == food.c.id).scalar_subquery().is_not(false())


def _layers(include: str | None) -> ColumnElement[bool]:
    return food.c.layer.in_(resolve.layers_for(include))


def _rank(cc: str | None) -> ColumnElement[int]:
    """A record's rank for the country's ordering: listed sources by position, an OFF record sold there
    just below them, everything else last. Used inside min(...), grouped by product, so any preferred
    record of a product counts. Without a country every record ranks the same."""
    if cc is None:
        return literal(0)
    sources = countries.PREFERRED.get(cc, ())
    n = len(sources)
    sold_there = case((food.c.markets.overlap(countries.off_markets(cc)), n), else_=n + 1)
    return case({s: i for i, s in enumerate(sources)} | {"off": sold_there}, value=food.c.source, else_=n + 1)


def by_name(q: str, include: str | None = None, limit: int = 20, country: str | None = None) -> list[dict]:
    # Word similarity: a short query against a long name ("beans" in "Beans, snap, green, raw"), over each
    # record's name and its names in other languages (`food_name`: "Vollkornbrot" finds BLS's wholemeal bread).
    # Each name index yields its best CANDIDATES rows in the final order first; only those pay the visibility
    # check (a correlated lookup per row: over 16k OFF matches for "rye bread" it was most of a second).
    # ponytail: a product whose every top-ranked record is invisible can fall past the cut; CANDIDATES per
    # result row keeps that far below `limit`.
    cc = countries.code(country)
    rk = _rank(cc)
    # A literal, not a bound parameter, so the planner can use the core-only name index.
    layer = _layers(include) if include == "off" else food.c.layer == literal_column("'core'")

    def best(name, source) -> Select:
        sim, length = func.word_similarity(q, name), func.length(name)
        return (select(food.c.id, sim.label("sim"), length.label("len"), rk.label("rk"))
                .select_from(source).where(layer, literal(q).op("<%")(name))
                .order_by(sim.desc(), *([rk] if cc else []), length).limit(limit * CANDIDATES))

    cand = union_all(best(food.c.name, food),
                     best(food_name.c.name, food_name.join(food, food.c.id == food_name.c.food_id))).cte("cand")
    return resolve.products(_pids(
        select(food.c.product_id).select_from(cand.join(food, food.c.id == cand.c.id))
        .where(_visible()).group_by(food.c.product_id)
        .order_by(func.max(cand.c.sim).desc(), func.min(cand.c.rk), func.min(cand.c.len)).limit(limit)
    ), include)


def by_record(record_id: str, include: str | None = None) -> list[dict]:
    """The product a source record (e.g. "fdc:174289", "off:0…") belongs to: one, or none."""
    return resolve.products(_pids(
        select(food.c.product_id).where(food.c.id == record_id, _layers(include), _visible())), include)


def by_barcode(code: str, include: str | None = None, country: str | None = None) -> list[dict]:
    """The products carrying a normalized GTIN-14, the country's preferred sources first."""
    found = select(food.c.product_id).where(food.c.gtin14 == code, _layers(include), _visible())
    if (cc := countries.code(country)) is None:
        stmt = found.distinct()
    else:
        stmt = found.group_by(food.c.product_id).order_by(func.min(_rank(cc)))
    return resolve.products(_pids(stmt), include)
