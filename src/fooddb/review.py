"""The review queue: values a failed check held back, and the decision that moves each one out.
The API, the MCP server and the admin UI all call these two functions."""

from typing import Literal

from sqlalchemy import func, select, text, update

from fooddb import resolve
from fooddb.db import engine, observation

STATUS = {"accept": "accepted", "reject": "rejected"}


class NotPending(ValueError):
    pass


def queue(limit: int = 100) -> list[dict]:
    """Pending values grouped per source record, newest first, next to the values the API serves now
    and the checks the record failed."""
    with engine().connect() as conn:
        rows = conn.execute(text("""
            with recs as (
                select food_id from observation where status = 'pending'
                group by food_id order by max(observed_at) desc, food_id limit :limit
            )
            select o.id, o.food_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.observed_at,
                   f.product_id, f.layer, f.name, f.source, f.flags
            from recs join observation o on o.food_id = recs.food_id and o.status = 'pending'
            join food f on f.id = o.food_id
            order by o.observed_at desc, o.food_id, o.nutrient
        """), {"limit": limit}).mappings().all()
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
