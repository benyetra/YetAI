"""Anonymous vault page-view events for pilot measurement."""

from alembic import op
import sqlalchemy as sa

revision = "20260806_lv_vault_events"
down_revision = "20260806_lv_tx_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lv_vault_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["lv_sites.id"]),
    )
    op.create_index("ix_lv_vault_events_id", "lv_vault_events", ["id"])
    op.create_index("ix_lv_vault_events_site_id", "lv_vault_events", ["site_id"])
    op.create_index("ix_lv_vault_events_slug", "lv_vault_events", ["slug"])
    op.create_index("ix_lv_vault_events_created_at", "lv_vault_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("lv_vault_events")
