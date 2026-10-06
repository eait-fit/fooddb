"""Developer portal: accounts that own API keys and hold prepaid request credits, Stripe purchases, magic-link
login tokens (hash only) and a monthly request counter.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("credits", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("unlimited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stripe_customer_id", sa.Text),
        sa.CheckConstraint("email = lower(email)", name="account_email_lower"),
        sa.CheckConstraint("credits >= 0", name="account_credits"),
    )
    op.add_column("api_key", sa.Column("account_id", sa.BigInteger, sa.ForeignKey("account.id")))
    op.create_index("api_key_account_idx", "api_key", ["account_id"])
    op.create_table(
        "purchase",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("account.id"), nullable=False),
        sa.Column("stripe_session_id", sa.Text, nullable=False, unique=True),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.Text, nullable=False),
        sa.Column("credits", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("purchase_account_idx", "purchase", ["account_id"])
    op.create_table(
        "login_token",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("account.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "usage_month",
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("account.id"), primary_key=True),
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("requests", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("usage_month")
    op.drop_table("login_token")
    op.drop_table("purchase")
    op.drop_index("api_key_account_idx", "api_key")
    op.drop_column("api_key", "account_id")
    op.drop_table("account")
