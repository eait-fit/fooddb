"""Finding products: by name, by source record, by barcode. Each returns the products in answer order,
as `resolve.products` serves them; what a miss means is the caller's (the API's 404, the CLI's exit 1)."""

from sqlalchemy import ColumnElement, Select, and_, case, false, func, literal, literal_column, select, union_all
from sqlalchemy.dialects.postgresql import distinct_on

from fooddb import countries, resolve, stems, synonyms
from fooddb.db import engine, food, food_name, observation

CANDIDATES = 20  # name rows ranked per result row before the visibility check

# Whole words that mark a name as a processed variant rather than the plain food (#115). A name
# carrying one of them loses to a plainer name when the query never asked for it ("Egg, white,
# dried" for "egg whites", "Babyfood, juice, orange" for "orange").
PROCESSING = ("mix", "mixture", "babyfood", "dried", "powder", "alcoholic",
              "juice", "nectar", "oil", "flour", "bran", "sugared", "gluten-free")


def _pids(stmt: Select) -> list[int]:
    with engine().connect() as conn:
        return list(conn.execute(stmt).scalars())


def _visible() -> ColumnElement[bool]:
    """A record shows when no value of it is accepted-less: some accepted value, or none at all (resolve.VISIBLE)."""
    o = observation.alias("o")
    return select(func.bool_or(o.c.status == "accepted")).where(o.c.food_id == food.c.id).scalar_subquery().is_not(false())


def _layers(include: str | None) -> ColumnElement[bool]:
    return food.c.layer.in_(resolve.layers_for(include))


def _penalty(name: ColumnElement, uq: ColumnElement) -> ColumnElement[int]:
    """How many PROCESSING words a name carries that the query did not ask for (#115). Whole-word
    match on the unaccented lowercase of both, so "mixture" never counts as "mix" and "nonfat"
    never as "fat"."""
    un, q = func.lower(func.f_unaccent(name)), func.lower(uq)
    pen = literal(0)
    for word in PROCESSING:
        pat = f"\\m{word}\\M"
        pen = pen + case((and_(un.op("~")(pat), q.op("!~")(pat)), 1), else_=0)
    return pen


def _rank(cc: str | None) -> ColumnElement[int]:
    """A record's rank for the country's ordering: listed sources by position, an OFF record sold there
    just below them, everything else last. Compared inside a product's candidate tuples, so any
    preferred record of a product counts. Without a country every record ranks the same."""
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

    # The country's synonyms add query variants (Erdäpfel → Kartoffel for `at`): each is searched
    # the same way and a product keeps its best score, whichever variant found it.
    variants = synonyms.expand(q, cc)
    named = food_name.join(food, food.c.id == food_name.c.food_id)

    def best(name, source, variant) -> Select:
        # f_unaccent on both sides: the query may carry the marks or lack them, so may the name.
        uq, un = func.f_unaccent(variant), func.f_unaccent(name)
        sim = func.word_similarity(uq, un)
        pen, length = _penalty(name, uq), func.length(name)
        return (select(food.c.id, sim.label("sim"), pen.label("pen"),
                       length.label("len"), rk.label("rk"))
                .select_from(source).where(layer, uq.op("<%")(un))
                .order_by(sim.desc(), pen, *([rk] if cc else []), length)
                .limit(limit * CANDIDATES))

    cand = union_all(*(best(name, source, v) for v in variants
                       for name, source in ((food.c.name, food), (food_name.c.name, named)))).cte("cand")
    # A product orders by its ONE best candidate tuple, (sim, pen, rk, len) in the cut's own order —
    # not three independent aggregates: a deeper cut can add a short name from a record that did not
    # give the best similarity, and max(sim)/min(rk)/min(len) would mix the tuples of two records,
    # so the first rows moved with `limit` ("orange" → Candied orange peel at limit=5).
    top = (select(food.c.product_id, cand.c.sim, cand.c.pen, cand.c.rk, cand.c.len)
           .select_from(cand.join(food, food.c.id == cand.c.id)).where(_visible())
           .ext(distinct_on(food.c.product_id))
           .order_by(food.c.product_id, cand.c.sim.desc(), cand.c.pen, cand.c.rk, cand.c.len)).cte("top")
    items = resolve.products(_pids(
        select(top.c.product_id).order_by(top.c.sim.desc(), top.c.pen, top.c.rk, top.c.len).limit(limit)
    ), include)
    # Inflection and compounds (#161): a query the trigram path could not reach at all tries
    # again on word stems — the same ranking, only ever adding answers, never moving them.
    return items or _by_stems(q, include, limit, cc, rk, layer, variants)


def _by_stems(q, include, limit, cc, rk, layer, variants) -> list[dict]:
    """The empty-result fallback on stemmed lexemes (see stems.py): every variant searched
    once per name index, ranked by the same tuple; "laksefilet" then meets "Laks, filet"."""
    named = food_name.join(food, food.c.id == food_name.c.food_id)

    def best(variant, scored, name, tname, source) -> Select:
        uq, un = func.f_unaccent(scored), func.f_unaccent(name)
        sim = func.word_similarity(uq, un)
        pen, length = _penalty(name, uq), func.length(name)
        return (select(food.c.id, sim.label("sim"), pen.label("pen"),
                       length.label("len"), rk.label("rk"))
                .select_from(source)
                .where(layer, stems.tsv(tname).op("@@")(stems.tsquery(variant)))
                .order_by(sim.desc(), pen, *([rk] if cc else []), length)
                .limit(limit * CANDIDATES))

    cand = union_all(*(best(v, s, n, t, src) for v, s in stems.variants(q, cc, variants)
                       for n, t, src in ((food.c.name, food, food),
                                         (food_name.c.name, food_name, named)))).cte("cand")
    top = (select(food.c.product_id, cand.c.sim, cand.c.pen, cand.c.rk, cand.c.len)
           .select_from(cand.join(food, food.c.id == cand.c.id)).where(_visible())
           .ext(distinct_on(food.c.product_id))
           .order_by(food.c.product_id, cand.c.sim.desc(), cand.c.pen, cand.c.rk, cand.c.len)).cte("top")
    return resolve.products(_pids(
        select(top.c.product_id).order_by(top.c.sim.desc(), top.c.pen, top.c.rk, top.c.len).limit(limit)
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
