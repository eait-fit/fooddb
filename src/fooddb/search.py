"""Finding products: by name, by source record, by barcode. Each returns the products in answer order,
as `resolve.products` serves them; what a miss means is the caller's (the API's 404, the CLI's exit 1)."""

import re

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

# Whole words that mark a name as a dish made of the food, a derivative of it or a diet/fat
# variant — the class-1 layer on top of processing words (#161). A name carrying one loses to a
# plainer name only when the query never asked for it, so "pie" never hurts "apple pie" and
# "sweetened" never hurts "sweetened soy milk". Multilingual: the per-language lists are small
# because each word is inert for a query that names the dish ("suppe" for "suppe").
DISH = (
    # English dishes and derivatives
    "pie", "nog", "dip", "stock", "broth", "spread", "compote", "goulash", "stew",
    "salad", "casserole", "strudel", "torte", "tart", "wrap", "sandwich",
    "cake", "cookie", "cookies", "muffin", "pancake", "pancakes", "waffle", "waffles",
    "pastry", "pastries", "dumpling", "dumplings", "pudding", "parfait", "smoothie",
    "shake", "sundae", "brownie", "trifle", "mousse", "curry", "ragu", "wok", "gratin",
    "quiche", "omelette", "crepe", "galette", "flan", "chutney", "relish",
    "preserves", "jam", "jelly", "ketchup", "dressing", "marinade", "sushi",
    "taco", "burrito", "burger", "kebab", "risotto", "paella",
    "rice", "breaded", "battered",
    "coated", "stuffed", "filled", "butter", "cream", "milk", "paste", "extract",
    "essence", "chips", "pretzel",
    # fat/light/variant markers — the plain form never names them
    "light", "lite", "reduced fat", "low fat", "fat free",
    "nonfat", "skimmed", "skim", "frosted", "honey", "imitation",
    # German
    "salat", "suppe", "auflauf", "eintopf", "gulasch", "ragout", "kuchen",
    "pfannkuchen",
    # Russian / Kazakh (agent-written names keep natural order)
    "пирог", "суп", "салат", "запеканка", "каша", "блины", "оладьи", "вареники",
    "плов", "гуляш", "борщ", "щи", "окрошка", "шарлотка", "торт", "печенье",
    "кекс", "омлет", "соус", "компот", "морс", "кисель", "жюльен", "рагу",
    "котлета", "котлеты", "пюре",
    # Spanish
    "sopa", "ensalada", "pastel", "tarta", "guiso", "estofado", "tortilla",
    "empanada", "galleta", "bizcocho", "puré",
    # French
    "soupe", "salade", "tarte", "gâteau", "ragoût", "potage", "velouté",
    "galette", "confiture",
    # Danish / Norwegian
    "gryte", "gryderet", "tærte", "kage", "pannekake", "pannekaker", "lapskaus",
    "omelett", "suppe",
    # Swedish
    "soppa", "sallad", "gryta", "paj", "kaka", "pannkaka", "pannkakor", "gratäng",
    # Dutch / Italian / Portuguese / Finnish
    "soep", "salade", "taart", "stamppot", "ovenschotel", "pannenkoek", "omelet",
    "zuppa", "insalata", "torta", "sugo", "frittata", "crostata",
    "sopa", "salada", "torta", "guisado",
    "keitto", "salaatti", "piirakka", "pata", "kastike", "munakas", "lettu",
)


def _pids(stmt: Select) -> list[int]:
    with engine().connect() as conn:
        return list(conn.execute(stmt).scalars())


def _visible() -> ColumnElement[bool]:
    """A record shows when no value of it is accepted-less: some accepted value, or none at all (resolve.VISIBLE)."""
    o = observation.alias("o")
    return select(func.bool_or(o.c.status == "accepted")).where(o.c.food_id == food.c.id).scalar_subquery().is_not(false())


def _layers(include: str | None) -> ColumnElement[bool]:
    return food.c.layer.in_(resolve.layers_for(include))


def _penalty(name: ColumnElement, uq: ColumnElement, words=PROCESSING) -> ColumnElement[int]:
    """How many of the listed words a name carries that the query did not ask for (#115, #161).
    Whole-word match on the unaccented lowercase of both, so "mixture" never counts as "mix"
    and "nonfat" never as "fat"."""
    un, q = func.lower(func.f_unaccent(name)), func.lower(uq)
    pen = literal(0)
    for word in words:
        # A space or a hyphen inside the entry matches either separator in the text —
        # "low fat" counts "Milk, low-fat" and a "low-fat milk" query asks for "low fat".
        pat = "\\m" + "[- ]".join(re.escape(p) for p in re.split(r"[ -]", word)) + "\\M"
        pen = pen + case((and_(un.op("~")(pat), q.op("!~")(pat)), 1), else_=0)
    return pen


def _cover(name: ColumnElement, words: list[str]) -> ColumnElement[int]:
    """0 when every query word appears as a whole word in the name, else 1 (#161 class 1):
    "canned salmon" keeps "Fish, salmon, canned" over "Salmon, smoked" — the query is covered,
    the head position does not matter (a category head and a wrong-food head are identical
    positionally, which is why a blunt head-first lost hit@1 when it was tried in #158)."""
    un = func.lower(func.f_unaccent(name))
    pats = []
    for w in words:
        forms = [w]
        if len(w) > 4 and w.endswith("es"):
            forms.append(w[:-2])
        elif len(w) > 3 and w.endswith("s"):
            forms.append(w[:-1])
        pats.append("\\m(" + "|".join(forms) + ")\\M")
    return case((and_(*(un.op("~")(p) for p in pats)), 0), else_=1)


def _words(variant: str) -> list[str]:
    from fooddb.stems import _unaccent
    return re.findall(r"[\wÀ-ÿ]+", _unaccent(variant.lower()))


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
        cov, dpen = _cover(name, _words(variant)), _penalty(name, uq, DISH)
        return (select(food.c.id, sim.label("sim"), cov.label("cov"), pen.label("pen"),
                       dpen.label("dpen"), length.label("len"), rk.label("rk"))
                .select_from(source).where(layer, uq.op("<%")(un))
                .order_by(sim.desc(), cov, pen, dpen, *([rk] if cc else []), length)
                .limit(limit * CANDIDATES))

    cand = union_all(*(best(name, source, v) for v in variants
                       for name, source in ((food.c.name, food), (food_name.c.name, named)))).cte("cand")
    # A product orders by its ONE best candidate tuple, (sim, cov, pen, dpen, rk, len) in the
    # cut's own order — not three independent aggregates: a deeper cut can add a short name
    # from a record that did not give the best similarity, and max(sim)/min(rk)/min(len)
    # would mix the tuples of two records, so the first rows moved with `limit`
    # ("orange" → Candied orange peel at limit=5).
    top = (select(food.c.product_id, cand.c.sim, cand.c.cov, cand.c.pen, cand.c.dpen,
                  cand.c.rk, cand.c.len)
           .select_from(cand.join(food, food.c.id == cand.c.id)).where(_visible())
           .ext(distinct_on(food.c.product_id))
           .order_by(food.c.product_id, cand.c.sim.desc(), cand.c.cov, cand.c.pen,
                     cand.c.dpen, cand.c.rk, cand.c.len)).cte("top")
    items = resolve.products(_pids(
        select(top.c.product_id).order_by(top.c.sim.desc(), top.c.cov, top.c.pen,
                                          top.c.dpen, top.c.rk, top.c.len).limit(limit)
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
        cov, dpen = _cover(name, _words(scored)), _penalty(name, uq, DISH)
        return (select(food.c.id, sim.label("sim"), cov.label("cov"), pen.label("pen"),
                       dpen.label("dpen"), length.label("len"), rk.label("rk"))
                .select_from(source)
                .where(layer, stems.tsv(tname).op("@@")(stems.tsquery(variant)))
                .order_by(sim.desc(), cov, pen, dpen, *([rk] if cc else []), length)
                .limit(limit * CANDIDATES))

    cand = union_all(*(best(v, s, n, t, src) for v, s in stems.variants(q, cc, variants)
                       for n, t, src in ((food.c.name, food, food),
                                         (food_name.c.name, food_name, named)))).cte("cand")
    top = (select(food.c.product_id, cand.c.sim, cand.c.cov, cand.c.pen, cand.c.dpen,
                  cand.c.rk, cand.c.len)
           .select_from(cand.join(food, food.c.id == cand.c.id)).where(_visible())
           .ext(distinct_on(food.c.product_id))
           .order_by(food.c.product_id, cand.c.sim.desc(), cand.c.cov, cand.c.pen,
                     cand.c.dpen, cand.c.rk, cand.c.len)).cte("top")
    return resolve.products(_pids(
        select(top.c.product_id).order_by(top.c.sim.desc(), top.c.cov, top.c.pen,
                                          top.c.dpen, top.c.rk, top.c.len).limit(limit)
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
