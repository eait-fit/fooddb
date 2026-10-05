"""Schema and engine.

`product` is one real-world product or food. `food` is one source record, linked to
the product matching assigned it to. `observation` is append-only: one value per
source record, nutrient and observation time, never updated (null = withdrawn).
`fooddb.resolve` picks the served value per product and field.
"""

import os
from functools import cache

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import Engine

metadata = MetaData()

product = Table(
    "product",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("merged_into", BigInteger, ForeignKey("product.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("product_merged_into_idx", "merged_into"),
)

food = Table(
    "food",
    metadata,
    Column("id", Text, primary_key=True),  # "<source>:<code>"
    Column("product_id", BigInteger, ForeignKey("product.id"), nullable=False),
    Column("source", Text, nullable=False),
    Column("layer", Text, nullable=False),  # "core" or "off" (ODbL)
    Column("licence", Text, nullable=False),
    Column("gtin14", Text),
    Column("name", Text, nullable=False),
    Column("brand", Text),
    Column("lang", Text),
    Column("serving_text", Text),
    Column("serving_g", Numeric),
    Column("flags", ARRAY(Text), nullable=False, server_default="{}"),
    Column("source_updated_at", DateTime(timezone=True)),
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("food_gtin14_idx", "gtin14"),
    Index("food_product_idx", "product_id"),
    Index("food_name_trgm_idx", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
)

observation = Table(
    "observation",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("food_id", Text, ForeignKey("food.id"), nullable=False),
    Column("nutrient", Text, nullable=False),  # FAO INFOODS tagname
    Column("value_per_100", Numeric),  # null = the source withdrew this field
    Column("unit", Text, nullable=False),
    Column("basis", Text, nullable=False, server_default="100g"),  # "100g" | "100ml"
    Column("status", Text, nullable=False, server_default="accepted"),  # accepted | pending | rejected
    Column("source", Text, nullable=False),
    Column("licence", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("food_id", "nutrient", "source", "observed_at", name="observation_once"),
)

fetch_run = Table(
    "fetch_run",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("fetcher", Text, nullable=False),
    Column("ref", Text, nullable=False),  # file name or release the run consumed
    Column("status", Text, nullable=False),  # running | done | failed
    Column("foods", Integer, nullable=False, server_default="0"),
    Column("observations", Integer, nullable=False, server_default="0"),
    Column("error", Text),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
)


def database_url() -> str:
    # No default: a default is slot 0's database, which a linked worktree must never touch.
    url = os.environ.get("FOODDB__BACKEND__DATABASE_URL")
    if not url:
        raise RuntimeError("FOODDB__BACKEND__DATABASE_URL is unset; run through ./dev (./dev cli …) or export it")
    return url


@cache
def engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)
