"""The review writes: the queue of values a failed check held back with the decision that moves
each one out, and the split that undoes a wrong merge. The API, the MCP server and the admin UI all
call these functions."""

from typing import Literal

from sqlalchemy import func, select, text, update

from fooddb import resolve
from fooddb.db import engine, merge_log, observation

STATUS = {"accept": "accepted", "reject": "rejected"}


class NotPending(ValueError):
    pass


class MergedAway(ValueError):
    pass


def queue(limit: int = 100, records: str = "%") -> list[dict]:
    """Pending values grouped per source record, newest first, next to the values the API serves now
    and the checks the record failed. `records` is a LIKE pattern on the record id, e.g. "label:%"."""
    with engine().connect() as conn:
        rows = conn.execute(text("""
            with recs as (
                select food_id from observation where status = 'pending' and food_id like :records
                group by food_id order by max(observed_at) desc, food_id limit :limit
            )
            select o.id, o.food_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.observed_at,
                   f.product_id, f.layer, f.name, f.source, f.flags
            from recs join observation o on o.food_id = recs.food_id and o.status = 'pending'
            join food f on f.id = o.food_id
            order by o.observed_at desc, o.food_id, o.nutrient
        """), {"limit": limit, "records": records}).mappings().all()
    items: dict[str, dict] = {}
    for r in rows:
        item = items.setdefault(r["food_id"], {
            "record": r["food_id"], "product_id": r["product_id"], "layer": r["layer"], "name": r["name"],
            "source": r["source"], "checks": list(r["flags"]), "pending": [], "served": {}})
        item["pending"].append({
            "observation_id": r["id"], "nutrient": r["nutrient"], "unit": r["unit"], "basis": r["basis"],
            "value": None if r["value_per_100"] is None else float(r["value_per_100"]),
            "observed_at": r["observed_at"]})
    for layer, include in (("core", None), ("off", "off")):
        pids = [i["product_id"] for i in items.values() if i["layer"] == layer]
        for p in resolve.products(pids, include):
            for rid in p["records"]:
                if rid in items and items[rid]["layer"] == layer:
                    items[rid]["served"] = p["per_100"]
    return list(items.values())


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
