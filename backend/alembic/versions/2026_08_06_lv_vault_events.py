"""Anonymous vault page-view events for pilot measurement.

Idempotent: prod may already have ``lv_vault_events`` from an earlier
partial create / ``create_all`` without this revision stamped.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260806_lv_vault_events"
down_revision = "20260806_lv_tx_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "lv_vault_events" not in existing:
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

    # Indexes — create if missing (table may pre-exist without them)
    idxs = {ix["name"] for ix in inspect(bind).get_indexes("lv_vault_events")}
    if "ix_lv_vault_events_id" not in idxs:
        op.create_index("ix_lv_vault_events_id", "lv_vault_events", ["id"])
    if "ix_lv_vault_events_site_id" not in idxs:
        op.create_index("ix_lv_vault_events_site_id", "lv_vault_events", ["site_id"])
    if "ix_lv_vault_events_slug" not in idxs:
        op.create_index("ix_lv_vault_events_slug", "lv_vault_events", ["slug"])
    if "ix_lv_vault_events_created_at" not in idxs:
        op.create_index(
            "ix_lv_vault_events_created_at", "lv_vault_events", ["created_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "lv_vault_events" in set(inspect(bind).get_table_names()):
        op.drop_table("lv_vault_events")
