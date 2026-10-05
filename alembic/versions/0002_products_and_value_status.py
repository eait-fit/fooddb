"""Products as matched entities; per-value basis, licence, review status and withdrawal.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("id", sa.BigInteger, primary_key=True),
        # Set when matching merges this product into another; reads follow it.
        sa.Column("merged_into", sa.BigInteger, sa.ForeignKey("product.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("food", sa.Column("product_id", sa.BigInteger, sa.ForeignKey("product.id")))
    # Every existing source record starts as its own product; matching merges them.
    op.execute("alter table product add column seed_food_id text")
    op.execute("insert into product (seed_food_id) select id from food")
    op.execute("update food f set product_id = p.id from product p where p.seed_food_id = f.id")
    op.execute("alter table product drop column seed_food_id")
    op.alter_column("food", "product_id", nullable=False)
    op.create_index("food_product_idx", "food", ["product_id"])

    op.alter_column("observation", "value_per_100", nullable=True)  # null = withdrawn by the source
    op.add_column("observation", sa.Column("basis", sa.Text, nullable=False, server_default="100g"))
    op.add_column("observation", sa.Column("status", sa.Text, nullable=False, server_default="accepted"))
    op.add_column("observation", sa.Column("licence", sa.Text))
    op.execute("update observation o set licence = f.licence from food f where f.id = o.food_id")
    op.alter_column("observation", "licence", nullable=False)
    op.create_check_constraint("observation_status", "observation", "status in ('accepted', 'pending', 'rejected')")
    op.create_check_constraint("observation_basis", "observation", "basis in ('100g', '100ml')")
    op.drop_index("observation_food_idx", "observation")
    op.create_index("observation_latest_idx", "observation", ["food_id", "nutrient", sa.text("observed_at desc"), sa.text("id desc")])
    # Replaced by the per-product resolver query in fooddb.resolve.
    op.execute("drop view food_value")


def downgrade() -> None:
    raise NotImplementedError("0002 is not reversible; restore from a dump")
