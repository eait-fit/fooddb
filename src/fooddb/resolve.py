"""The resolver: one served value per product and field, across every source record of it.

Per source record, the newest accepted observation of each field counts (a null one means the
source withdrew it). Across records, `pick_sql` holds the rule: staleness, agreement, trust rank,
recency. The OFF layer (ODbL) takes part only when the caller asks for it, so licence follows each
value.
"""

import os
from datetime import date

from sqlalchemy import Connection, text

from fooddb.db import engine

# ponytail: fixed source ranks; a per-field trust table when brand uploads and label reads land.
RANK = "case {col} when 'brand' then 1 when 'label' then 2 when 'fdc' then 3 when 'off' then 4 else 9 end"

# Two values agree within 5 %, or within 0.5 of the unit for small values.
AGREE = "abs({a} - {b}) <= greatest(0.05 * greatest(abs({a}), abs({b})), 0.5)"
STALE_AFTER_DAYS = int(os.environ.get("FOODDB__BACKEND__STALE_AFTER_DAYS", "730"))


def pick_sql(candidates: str) -> str:
    """One value per product and nutrient from `candidates`, the resolver rule in one place.

    A value older than the newest candidate by more than STALE_AFTER_DAYS loses to fresher ones.
    Then the value that the most distinct sources agree with wins, then the most trusted source,
    then the newest value.
    """
    return f"""
with cand as (
    select c.*, row_number() over () as cid,
           max(c.observed_at) over (partition by c.product_id, c.nutrient) as newest
    from ({candidates}) c
), support as (
    select c.cid, count(distinct o.source) as sources
    from cand c join cand o on o.product_id = c.product_id and o.nutrient = c.nutrient
                           and {AGREE.format(a="o.value_per_100", b="c.value_per_100")}
    group by c.cid
)
select distinct on (c.product_id, c.nutrient)
       c.product_id, c.nutrient, c.value_per_100, c.unit, c.basis, c.source, c.licence, c.observed_at
from cand c join support s using (cid)
order by c.product_id, c.nutrient, c.observed_at < c.newest - interval '{STALE_AFTER_DAYS} days',
         s.sources desc, {RANK.format(col="c.source")}, c.observed_at desc, c.value_per_100
"""


def values_sql(products: str) -> str:
    """Resolved values for the products `products` selects (an SQL condition on f.product_id)."""
    return pick_sql(f"""
select * from (
    select distinct on (o.food_id, o.nutrient)
           f.product_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.source, o.licence, o.observed_at
    from observation o join food f on f.id = o.food_id
    where {products} and f.layer = any(:layers) and o.status = 'accepted'
    order by o.food_id, o.nutrient, o.observed_at desc, o.id desc
) latest
where value_per_100 is not null
""")


LIVE_SQL = values_sql("f.product_id = any(:pids)")
# A product merged after the build still has its values under its old id: read every id merged into
# each product, and pick across them by the resolver's rule, as if the merge had come before the build.
# ponytail: the snapshot keeps only each old id's winner, so agreement counts winners, not every value.
SNAPSHOT_SQL = f"""
with recursive member(product_id, id) as (
    select id, id from product where id = any(:pids)
    union all
    select m.product_id, p.id from member m join product p on p.merged_into = m.id
)
select * from ({pick_sql("""
    select m.product_id, v.nutrient, v.value_per_100, v.unit, v.basis, v.source, v.licence, v.observed_at
    from member m join snapshot_value v on v.product_id = m.id
    where v.day = :day and v.scope = :scope
""")}) picked
"""


class NoSnapshot(LookupError):
    pass

RECORDS_SQL = f"""
select product_id, id, source, licence, gtin14, name, brand, lang, serving_text, serving_g, flags, source_updated_at
from food
where product_id = any(:pids) and layer = any(:layers)
order by product_id, {RANK.format(col="source")}, source_updated_at desc nulls last
"""


FIELDS = ("name", "brand", "lang", "serving_text", "serving_g")


def tagged(record, value) -> dict | None:
    """A served field: its value with the source, licence and record it came from."""
    if value is None:
        return None
    return {"value": value, "source": record["source"], "licence": record["licence"], "record": record["id"]}


def layers_for(include: str | None) -> list[str]:
    return ["core", "off"] if include == "off" else ["core"]


def canonical(pids: list[int], conn: Connection) -> list[int]:
    """Follow merges: a product matching merged away answers as the one it was merged into."""
    if not pids:
        return []
    rows = dict(conn.execute(text("""
        with recursive chain(start, id, merged_into) as (
            select id, id, merged_into from product where id = any(:pids)
            union all
            select c.start, p.id, p.merged_into from chain c join product p on p.id = c.merged_into
        )
        select start, id from chain where merged_into is null
    """), {"pids": pids}).all())
    return list(dict.fromkeys(rows[p] for p in pids if p in rows))


def products(pids: list[int], include: str | None, snapshot: date | None = None,
             conn: Connection | None = None) -> list[dict]:
    """Resolved products in the order given; a product with no visible record is left out.

    Values come from the newest nightly snapshot (or the pinned `snapshot` day); live resolution
    only while no snapshot has been built yet. Which records make up a product is always live.
    ponytail: records and names are not snapshotted; pin them too if clients need full replay.
    """
    if conn is None:
        with engine().connect() as conn:
            return products(pids, include, snapshot, conn)
    pids = canonical(pids, conn)
    params = {"pids": pids, "layers": layers_for(include), "scope": "all" if include == "off" else "core"}
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
            p.update({f: tagged(r, r[f]) for f in FIELDS}, flags=tagged(r, list(r["flags"])), per_100={})
        p["records"].append(r["id"])
        if r["gtin14"] and r["gtin14"] not in [g["value"] for g in p["gtin14"]]:
            p["gtin14"].append(tagged(r, r["gtin14"]))
    for v in values:
        if v["product_id"] in by_pid:
            by_pid[v["product_id"]]["per_100"][v["nutrient"]] = {
                "value": float(v["value_per_100"]), "unit": v["unit"], "basis": v["basis"],
                "source": v["source"], "licence": v["licence"], "observed_at": v["observed_at"],
            }
    return [by_pid[p] for p in pids if p in by_pid]
