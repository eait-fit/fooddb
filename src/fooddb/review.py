"""The review writes: the queue of values a failed check held back with the decision that moves
each one out, and the split that undoes a wrong merge. The API, the MCP server and the admin UI all
call these functions."""

from typing import Literal

from sqlalchemy import func, select, text, update

from fooddb import checks, resolve
from fooddb.db import engine, merge_log, observation

STATUS = {"accept": "accepted", "reject": "rejected"}


class NotPending(ValueError):
    pass


class MergedAway(ValueError):
    pass


def queue(limit: int = 100, records: tuple[str, ...] = ("%",), *, offset: int = 0, check: str | None = None,
          source: str | None = None, detail: bool = False) -> list[dict]:
    """Pending values grouped per source record, newest first, next to the values the API serves now
    and the checks the record failed. `records` are LIKE patterns on the record id, e.g. ("label:%", "brand:%").
    `offset`, `check` and `source` page and filter the records. `detail` adds to each item the brand, all the
    record's latest values (`values`, any status) and one line per failed check with its numbers (`why`)."""
    with engine().connect() as conn:
        rows = conn.execute(text("""
            with recs as (
                select o.food_id from observation o join food f on f.id = o.food_id
                where o.status = 'pending' and o.food_id like any(:records)
                  and (cast(:check as text) is null or cast(:check as text) = any(f.flags))
                  and (cast(:source as text) is null or f.source = cast(:source as text))
                group by o.food_id order by max(o.observed_at) desc, o.food_id limit :limit offset :offset
            )
            select o.id, o.food_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.observed_at, o.evidence,
                   f.product_id, f.layer, f.name, f.brand, f.category, f.source, f.flags
            from recs join observation o on o.food_id = recs.food_id and o.status = 'pending'
            join food f on f.id = o.food_id
            order by o.observed_at desc, o.food_id, o.nutrient
        """), {"limit": limit, "offset": offset, "records": list(records), "check": check, "source": source}
        ).mappings().all()
    items: dict[str, dict] = {}
    for r in rows:
        item = items.setdefault(r["food_id"], {
            "record": r["food_id"], "product_id": r["product_id"], "layer": r["layer"], "name": r["name"],
            "source": r["source"], "photo": r["evidence"], "checks": list(r["flags"]), "pending": [], "served": {}}
            | ({"brand": r["brand"], "category": r["category"]} if detail else {}))
        item["pending"].append({
            "observation_id": r["id"], "nutrient": r["nutrient"], "unit": r["unit"], "basis": r["basis"],
            "value": None if r["value_per_100"] is None else float(r["value_per_100"]),
            "observed_at": r["observed_at"]})
    for layer, include in (("core", None), ("off", "off")):
        pids = [i["product_id"] for i in items.values() if i["layer"] == layer]
        for p in resolve.products(pids, include):
            for item in items.values():
                if item["layer"] == layer and item["product_id"] == p["id"]:
                    item["served"] = p["per_100"]  # a held record is not among p["records"], its product still serves
    if detail:
        _detail(items)
    return list(items.values())


def _detail(items: dict[str, dict]) -> None:
    """Each record's latest value per nutrient (whatever its status) and its pending values, and the checks explained
    from those latest values."""
    with engine().connect() as conn:
        rows = conn.execute(text("""
            with newest as (
                select distinct on (food_id, nutrient) id from observation where food_id = any(:ids)
                order by food_id, nutrient, observed_at desc, id desc
            )
            select o.id, o.food_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.status, o.observed_at,
                   o.id in (select id from newest) as latest
            from observation o
            where o.food_id = any(:ids) and (o.status = 'pending' or o.id in (select id from newest))
            order by o.food_id, o.nutrient, o.observed_at desc, o.id desc
        """), {"ids": list(items)}).mappings().all()
    for item in items.values():
        item["values"] = []
    for r in rows:
        items[r["food_id"]]["values"].append({
            "observation_id": r["id"], "nutrient": r["nutrient"], "unit": r["unit"], "basis": r["basis"],
            "status": r["status"], "observed_at": r["observed_at"], "latest": r["latest"],
            "value": None if r["value_per_100"] is None else float(r["value_per_100"])})
    for item in items.values():
        latest = [v for v in item["values"] if v["latest"] and v["value"] is not None]
        nums = {v["nutrient"]: v["value"] for v in latest}
        implicated = checks.flags(nums, item["category"], latest[0]["basis"] if latest else "100g")
        item["why"] = {c: checks.explain(c, nums, implicated.get(c, ())) for c in item["checks"]}


def facets(records: tuple[str, ...] = ("%",), check: str | None = None, source: str | None = None) -> dict:
    """What the records with pending values hold: how many (`total`, under both filters), and per check and per source
    how many records have it, each counted under the other filter."""
    pending = """select f.id, f.source, f.flags from food f where f.id like any(:records)
                 and exists (select 1 from observation o where o.food_id = f.id and o.status = 'pending')"""
    has_check = "(cast(:check as text) is null or cast(:check as text) = any(flags))"
    has_source = "(cast(:source as text) is null or source = cast(:source as text))"
    args = {"records": list(records), "check": check, "source": source}
    with engine().connect() as conn:
        total = conn.execute(text(f"with p as ({pending}) select count(*) from p where {has_check} and {has_source}"),
                             args).scalar_one()
        by_check = conn.execute(text(f"with p as ({pending}) select c, count(*) from p, unnest(flags) c "
                                     f"where {has_source} group by c order by 2 desc, 1"), args).all()
        by_source = conn.execute(text(f"with p as ({pending}) select source, count(*) from p where {has_check} "
                                      "group by source order by 2 desc, 1"), args).all()
    return {"total": total, "checks": dict(by_check), "sources": dict(by_source)}


def decide(observation_id: int, decision: Literal["accept", "reject"], by: str, note: str | None = None) -> dict:
    """Accept (the resolver may serve it from the next snapshot on) or reject (never served) one pending value."""
    o = observation.c
    with engine().begin() as conn:
        row = conn.execute(
            update(observation).where(o.id == observation_id, o.status == "pending")
            .values(status=STATUS[decision], reviewed_by=by, reviewed_at=func.now(), review_note=note)
            .returning(o.id, o.food_id, o.nutrient, o.status, o.reviewed_by, o.reviewed_at, o.review_note)
        ).mappings().first()
        if row is None:
            status = conn.execute(select(o.status).where(o.id == observation_id)).scalar_one_or_none()
            if status is None:
                raise LookupError(f"observation {observation_id} not found")
            raise NotPending(f"observation {observation_id} is already {status}")
    return dict(row)


# A record's home is the product ingest made for it: the source of its first logged merge.
HOMES_SQL = """
select coalesce((select from_product from merge_log where kind = 'merge' and f = any(food_ids) order by id limit 1),
                :pid)
from unnest(cast(:ids as text[])) f
"""


def split(product_id: int, food_ids: list[str], by: str, note: str | None = None) -> dict:
    """Move records out of a product that matching merged wrongly, into one product of their own.

    When every record has the same home and that home was merged into this product, the home gets
    its id back, so old links to it work again. Otherwise the records get a new product. Each moved
    record and each record that stays become a cannot-link pair: matching never joins them again.
    """
    ids = sorted(set(food_ids))
    with engine().begin() as conn:
        found = conn.execute(text("select merged_into from product where id = :id for update"), {"id": product_id}).first()
        if found is None:
            raise LookupError(f"product {product_id} not found")
        if found.merged_into is not None:
            raise MergedAway(f"product {product_id} was merged into {found.merged_into}: split that one")
        records = set(conn.execute(text("select id from food where product_id = :id"), {"id": product_id}).scalars())
        if not ids or not set(ids) <= records:
            raise ValueError(f"not records of product {product_id}: {sorted(set(ids) - records) or 'none given'}")
        if set(ids) == records:
            raise ValueError("a split leaves at least one record in the product")
        homes = set(conn.execute(text(HOMES_SQL), {"ids": ids, "pid": product_id}).scalars())
        home = homes.pop() if len(homes) == 1 else None
        restored = home is not None and home != product_id and resolve.canonical([home], conn) == [product_id]
        if restored:
            # Products merged into the home have their records here, not in the home: they keep following them.
            conn.execute(text("update product set merged_into = :p where merged_into = :h"), {"p": product_id, "h": home})
            conn.execute(text("update product set merged_into = null where id = :h"), {"h": home})
            target = home
        else:
            target = conn.execute(text("insert into product default values returning id")).scalar_one()
        conn.execute(text("update food set product_id = :t where id = any(:ids)"), {"t": target, "ids": ids})
        conn.execute(text("""
            insert into cannot_link (food_a, food_b, by, note)
            select least(a, b), greatest(a, b), :by, :note
            from unnest(cast(:moved as text[])) a cross join unnest(cast(:kept as text[])) b
            on conflict do nothing
        """), {"moved": ids, "kept": sorted(records - set(ids)), "by": by, "note": note})
        conn.execute(merge_log.insert().values(kind="split", from_product=product_id, into_product=target,
                                               food_ids=ids, by=by, note=note))
    return {"product_id": product_id, "split_into": target, "records": ids, "restored": restored}
