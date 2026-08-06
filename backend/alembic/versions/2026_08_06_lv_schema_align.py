"""Add any missing League Vault columns on prod tables created early.

Prod ``lv_*`` tables may predate later model fields (e.g. ``lv_drafts.status``)
because local P1 used ``create_all`` / an older shape, then Alembic stamped past
the create revision without ALTERing.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260806_lv_schema_align"
down_revision = "20260806_lv_matchup_scores"
branch_labels = None
depends_on = None


def _add_missing(table: str, columns: list[tuple[str, sa.types.TypeEngine]]) -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns(table)}
    for name, col_type in columns:
        if name not in existing:
            op.add_column(table, sa.Column(name, col_type, nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())

    if "lv_drafts" in tables:
        _add_missing(
            "lv_drafts",
            [
                ("platform_draft_id", sa.String(64)),
                ("draft_type", sa.String(64)),
                ("status", sa.String(64)),
                ("settings", sa.JSON()),
            ],
        )

    if "lv_draft_picks" in tables:
        cols = {c["name"] for c in inspect(bind).get_columns("lv_draft_picks")}
        # Prefer prod/PRD names pick_no + draft_slot
        if "pick" in cols and "pick_no" not in cols:
            op.alter_column(
                "lv_draft_picks",
                "pick",
                new_column_name="pick_no",
                existing_type=sa.Integer(),
                existing_nullable=False,
            )
            cols.discard("pick")
            cols.add("pick_no")
        if "overall_pick" in cols and "draft_slot" not in cols:
            op.alter_column(
                "lv_draft_picks",
                "overall_pick",
                new_column_name="draft_slot",
                existing_type=sa.Integer(),
                existing_nullable=True,
            )
            cols.discard("overall_pick")
            cols.add("draft_slot")
        _add_missing(
            "lv_draft_picks",
            [
                ("pick_no", sa.Integer()),
                ("draft_slot", sa.Integer()),
                ("platform_roster_id", sa.String(64)),
                ("player_id", sa.String(64)),
                ("team_id", sa.Integer()),
                ("is_keeper", sa.Boolean()),
                ("auction_amount", sa.Float()),
            ],
        )

    if "lv_matchups" in tables:
        _add_missing(
            "lv_matchups",
            [
                ("platform_matchup_id", sa.String(64)),
                ("playoff_round", sa.Integer()),
                ("bracket", sa.String(32)),
                ("team_a_score", sa.Float()),
                ("team_b_score", sa.Float()),
                ("winner_team_id", sa.Integer()),
                ("margin", sa.Float()),
            ],
        )

    if "lv_transactions" in tables:
        _add_missing(
            "lv_transactions",
            [
                ("week", sa.Integer()),
                ("status", sa.String(64)),
                ("created_at_ts", sa.BigInteger()),
                ("payload", sa.JSON()),
                ("team_ids", sa.JSON()),
            ],
        )


def downgrade() -> None:
    # Non-destructive align; leave columns in place.
    pass
