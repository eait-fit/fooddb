"""The resolver: one served value per product and field, across every source record of it.

Per source record, the newest accepted observation of each field counts (a null one means the
source withdrew it). Across records, `pick_sql` holds the rule: an approved label read first, then
staleness, agreement, trust rank, recency. The OFF layer (ODbL) takes part only when the caller asks for it, so licence follows each
value.
"""

import os
from datetime import date

from sqlalchemy import Connection, text

from fooddb import checks
from fooddb.db import engine
from fooddb.fetchers import ciqual, cofid, fineli, frida, matvaretabellen, mext

# ponytail: fixed source ranks; a per-field trust table when brand uploads and label reads land.
# The composition tables (FDC and the national ones) share one rank, above the crowd (OFF).
RANK = ("case {col} when 'brand' then 1 when 'label' then 2"
        " when 'fdc' then 3 when 'ciqual' then 3 when 'fineli' then 3 when 'matvaretabellen' then 3"
        " when 'mext' then 3"
        " when 'frida' then 3"
        " when 'cofid' then 3"
        " when 'off' then 4 else 9 end")

# Two values agree within 5 %, or within 0.5 of the unit for small values.
AGREE = "abs({a} - {b}) <= greatest(0.05 * greatest(abs({a}), abs({b})), 0.5)"
STALE_AFTER_DAYS = int(os.environ.get("FOODDB__BACKEND__STALE_AFTER_DAYS", "730"))


def pick_sql(candidates: str) -> str:
    """One value per product and nutrient from `candidates`, the resolver rule in one place.

    A label read that a reviewer approved wins outright; the newest of several does. Otherwise,
    a value older than the newest candidate by more than STALE_AFTER_DAYS loses to fresher ones.
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
       c.product_id, c.nutrient, c.value_per_100, c.unit, c.basis, c.source, c.licence, c.observed_at,
       c.approved
from cand c join support s using (cid)
order by c.product_id, c.nutrient, not c.approved, case when c.approved then c.observed_at end desc,
         c.observed_at < c.newest - interval '{STALE_AFTER_DAYS} days',
         s.sources desc, {RANK.format(col="c.source")}, c.observed_at desc, c.value_per_100
"""


def values_sql(products: str) -> str:
    """Resolved values for the products `products` selects (an SQL condition on f.product_id)."""
    return pick_sql(f"""
select * from (
    select distinct on (o.food_id, o.nutrient)
           f.product_id, o.nutrient, o.value_per_100, o.unit, o.basis, o.source, o.licence, o.observed_at,
           (o.source = 'label' and o.status = 'accepted' and o.reviewed_by is not null) as approved
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
# An approved label read always wins its old id, so the stored flag makes the override exact.
SNAPSHOT_SQL = f"""
with recursive member(product_id, id) as (
    select id, id from product where id = any(:pids)
    union all
    select m.product_id, p.id from member m join product p on p.merged_into = m.id
)
select * from ({pick_sql("""
    select m.product_id, v.nutrient, v.value_per_100, v.unit, v.basis, v.source, v.licence, v.observed_at, v.approved
    from member m join snapshot_value v on v.product_id = m.id
    where v.day = :day and v.scope = :scope
""")}) picked
"""

# A product that nothing was merged into has one candidate per nutrient in the snapshot: its stored winner.
# Only a product with merged-in ids needs SNAPSHOT_SQL. The rest is read as stored, by index, whatever the
# table statistics say.
MERGED_SQL = "select distinct merged_into from product where merged_into = any(:pids)"
STORED_SQL = """
select product_id, nutrient, value_per_100, unit, basis, source, licence, observed_at, approved
from snapshot_value
where day = :day and scope = :scope and product_id = any(:pids)
order by product_id, nutrient
"""


class NoSnapshot(LookupError):
    pass

# A record shapes the product (name, barcode, category, flags) and is found by lookups only once one of
# its values is accepted. A record with no observations at all has nothing to hold back.
# One correlated lookup per record: written as exists-or-not-exists, the planner hashes the accepted
# observations of the whole table once per query.
VISIBLE = "((select bool_or(o.status = 'accepted') from observation o where o.food_id = food.id) is not false)"
RECORDS_SQL = f"""
select product_id, id, source, licence, gtin14, name, brand, lang, serving_text,
       serving_g::float8 as serving_g, category, flags, source_updated_at
from food
where product_id = any(:pids) and layer = any(:layers) and {VISIBLE}
order by product_id, {RANK.format(col="source")}, source_updated_at desc nulls last
"""


FIELDS = ("name", "brand", "lang", "serving_text", "serving_g", "category")
# Least to most restrictive; an unknown licence counts as the most. The middle ones ask for attribution.
LICENCES = ("CC0-1.0", "etalab-2.0", "NLOD-2.0", "OGL-UK-3.0", "mext-free-use", "CC-BY-4.0", "ODbL-1.0")
# Sources whose licence asks every user of the data to name them: source → (licence, text).
ATTRIBUTION = {m.FETCHER: (m.LICENCE, m.ATTRIBUTION) for m in (ciqual, cofid, fineli, frida, matvaretabellen, mext)}


def tagged(record, value) -> dict | None:
    """A served field: its value with the source, licence and record it came from."""
    if value is None:
        return None
    return {"value": value, "source": record["source"], "licence": record["licence"], "record": record["id"]}


def seals(per_100: dict) -> dict | None:
    """The warning seals the served values imply (`checks.SEALS`), computed here and never stored.
    Its licence is the most restrictive among the values it read."""
    values = {n: v["value"] for n, v in per_100.items()}
    found, used = checks.seals(values, liquid=all(v["basis"] == "100ml" for v in per_100.values()))
    if not used:
        return None
    licence = max((per_100[n]["licence"] for n in used),
                  key=lambda lic: LICENCES.index(lic) if lic in LICENCES else len(LICENCES))
    return {"value": found, "source": "fooddb", "licence": licence, "record": None}


def attribution(p: dict) -> list[dict]:
    """The attribution that each source of a served field asks for, once per source."""
    tags = [*(p[f] for f in (*FIELDS, "flags")), *p["gtin14"], *p["per_100"].values()]
    return [{"source": s, "licence": ATTRIBUTION[s][0], "text": ATTRIBUTION[s][1]}
            for s in sorted({t["source"] for t in tags if t} & ATTRIBUTION.keys())]


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
    if day:
        merged = set(conn.execute(text(MERGED_SQL), params).scalars())
        values = conn.execute(text(STORED_SQL), params | {"day": day, "pids": [p for p in pids if p not in merged]}).mappings().all()
        if merged:
            values += conn.execute(text(SNAPSHOT_SQL), params | {"day": day, "pids": sorted(merged)}).mappings().all()
    else:
        values = conn.execute(text(LIVE_SQL), params).mappings().all()
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
    for found in by_pid.values():
        found["seals"] = seals(found["per_100"])
        found["attribution"] = attribution(found)
    return [by_pid[p] for p in pids if p in by_pid]
