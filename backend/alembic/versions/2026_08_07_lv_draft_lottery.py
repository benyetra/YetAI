"""Idempotent lv_draft_lottery for one-shot NBA-style draft order draws."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260807_lv_draft_lottery"
down_revision = "20260806_lv_schema_align"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "lv_draft_lottery" not in existing:
        op.create_table(
            "lv_draft_lottery",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("site_id", sa.Integer(), nullable=False),
            sa.Column("upcoming_season", sa.Integer(), nullable=False),
            sa.Column("source_season", sa.Integer(), nullable=False),
            sa.Column("drawn_at", sa.DateTime(), nullable=False),
            sa.Column("rng_seed", sa.String(length=64), nullable=False),
            sa.Column("seed_snapshot", sa.JSON(), nullable=False),
            sa.Column("drawn_order", sa.JSON(), nullable=False),
            sa.Column(
                "lottery_picks", sa.Integer(), nullable=False, server_default="3"
            ),
            sa.ForeignKeyConstraint(["site_id"], ["lv_sites.id"]),
            sa.UniqueConstraint(
                "site_id",
                "upcoming_season",
                name="uq_lv_draft_lottery_site_season",
            ),
        )

    idxs = {ix["name"] for ix in inspect(bind).get_indexes("lv_draft_lottery")}
    if "ix_lv_draft_lottery_id" not in idxs:
        op.create_index("ix_lv_draft_lottery_id", "lv_draft_lottery", ["id"])
    if "ix_lv_draft_lottery_site_id" not in idxs:
        op.create_index("ix_lv_draft_lottery_site_id", "lv_draft_lottery", ["site_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "lv_draft_lottery" in set(inspect(bind).get_table_names()):
        op.drop_table("lv_draft_lottery")
