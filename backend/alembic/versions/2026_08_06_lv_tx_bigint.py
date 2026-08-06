"""No-op: lv_transactions.created_at_ts is BigInteger in create migration."""

from alembic import op

revision = "20260806_lv_tx_bigint"
down_revision = "20260806_league_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # created_at_ts already uses BigInteger in 20260806_league_vault; keep chain linear.
    pass


def downgrade() -> None:
    pass
