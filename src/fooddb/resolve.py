"""The resolver: one served value per product and field, across every source record of it.

Per source record, the newest accepted observation of each field counts (a null one means the
source withdrew it). Across records, the most trusted source wins, then the newest value. The OFF
layer (ODbL) takes part only when the caller asks for it, so licence follows each value.
"""

from datetime import date

from sqlalchemy import text

from fooddb.db import engine

# ponytail: fixed source ranks; a per-field trust table when brand uploads and label reads land.
RANK = "case {col} when 'brand' then 1 when 'label' then 2 when 'fdc' then 3 when 'off' then 4 else 9 end"

def values_sql(products: str) -> str:
    """Resolved values for the products `products` selects (an SQL condition on f.product_id)."""
    return f"""
with latest as (
    select distinct on (o.food_id, o.nutrient)
           f.product_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.source, o.licence, o.observed_at
    from observation o join food f on f.id = o.food_id
    where {products} and f.layer = any(:layers) and o.status = 'accepted'
    order by o.food_id, o.nutrient, o.observed_at desc, o.id desc
)
select distinct on (product_id, nutrient) *
from latest
where value_per_100 is not null
order by product_id, nutrient, {RANK.format(col="source")}, observed_at desc
"""


LIVE_SQL = values_sql("f.product_id = any(:pids)")
SNAPSHOT_SQL = """
select product_id, nutrient, value_per_100, unit, basis, source, licence, observed_at
from snapshot_value where day = :day and scope = :scope and product_id = any(:pids)
"""


class NoSnapshot(LookupError):
    pass

RECORDS_SQL = f"""
select product_id, id, source, licence, gtin14, name, brand, lang, serving_text, serving_g, flags, source_updated_at
from food
where product_id = any(:pids) and layer = any(:layers)
order by product_id, {RANK.format(col="source")}, source_updated_at desc nulls last
"""


def layers_for(include: str | None) -> list[str]:
    return ["core", "off"] if include == "off" else ["core"]


def canonical(pids: list[int]) -> list[int]:
    """Follow merges: a product matching merged away answers as the one it was merged into."""
    if not pids:
        return []
    with engine().connect() as conn:
        rows = dict(conn.execute(text("""
            with recursive chain(start, id, merged_into) as (
                select id, id, merged_into from product where id = any(:pids)
                union all
                select c.start, p.id, p.merged_into from chain c join product p on p.id = c.merged_into
            )
            select start, id from chain where merged_into is null
        """), {"pids": pids}).all())
    return list(dict.fromkeys(rows[p] for p in pids if p in rows))


def products(pids: list[int], include: str | None, snapshot: date | None = None) -> list[dict]:
    """Resolved products in the order given; a product with no visible record is left out.

    Values come from the newest nightly snapshot (or the pinned `snapshot` day); live resolution
    only while no snapshot has been built yet. Which records make up a product is always live.
    ponytail: records and names are not snapshotted; pin them too if clients need full replay.
    """
    pids = canonical(pids)
    params = {"pids": pids, "layers": layers_for(include), "scope": "all" if include == "off" else "core"}
    with engine().connect() as conn:
        day = snapshot or conn.execute(text("select max(day) from snapshot")).scalar_one()
        if snapshot and not conn.execute(text("select 1 from snapshot where day = :d"), {"d": snapshot}).first():
            raise NoSnapshot(f"no snapshot for {snapshot.isoformat()}")
        records = conn.execute(text(RECORDS_SQL), params).mappings().all()
        values = conn.execute(text(SNAPSHOT_SQL if day else LIVE_SQL), params | {"day": day}).mappings().all()
    by_pid: dict[int, dict] = {}
    for r in records:
        p = by_pid.setdefault(r["product_id"], {"id": r["product_id"], "records": [], "gtin14": [],
                                                "snapshot": day.isoformat() if day else None})
        if not p["records"]:  # the most trusted, newest record names the product
            p.update(name=r["name"], brand=r["brand"], lang=r["lang"], serving_text=r["serving_text"],
                     serving_g=r["serving_g"], flags=list(r["flags"]), per_100={})
        p["records"].append(r["id"])
        if r["gtin14"] and r["gtin14"] not in p["gtin14"]:
            p["gtin14"].append(r["gtin14"])
    for v in values:
        if v["product_id"] in by_pid:
            by_pid[v["product_id"]]["per_100"][v["nutrient"]] = {
                "value": float(v["value_per_100"]), "unit": v["unit"], "basis": v["basis"],
                "source": v["source"], "licence": v["licence"], "observed_at": v["observed_at"],
            }
    return [by_pid[p] for p in pids if p in by_pid]
