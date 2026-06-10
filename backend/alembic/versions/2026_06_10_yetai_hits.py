"""Add pred_yetai_hits for tracked highlighted player prop plays.

Revision ID: 20260610_yetai_hits
Revises: 20260607_pa_game_script
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260610_yetai_hits"
down_revision = "20260607_pa_game_script"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("pred_yetai_hits"):
        return
    op.create_table(
        "pred_yetai_hits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sport", sa.String(length=16), nullable=False),
        sa.Column("stat_type", sa.String(length=32), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("entity_name", sa.String(length=120), nullable=False),
        sa.Column("opponent_name", sa.String(length=120), nullable=True),
        sa.Column("projected_value", sa.Float(), nullable=False),
        sa.Column("market_line", sa.Float(), nullable=False),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("pick", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("value_tier", sa.String(length=16), nullable=False),
        sa.Column("projection_row_id", sa.Integer(), nullable=True),
        sa.Column("actual_value", sa.Float(), nullable=True),
        sa.Column("hit_result", sa.String(length=16), nullable=True),
        sa.Column("graded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sport",
            "stat_type",
            "game_date",
            "entity_id",
            name="unique_yetai_hit",
        ),
    )
    op.create_index("idx_yetai_hits_sport_date", "pred_yetai_hits", ["sport", "game_date"])
    op.create_index("idx_yetai_hits_result", "pred_yetai_hits", ["hit_result"])


def downgrade() -> None:
    if not _has_table("pred_yetai_hits"):
        return
    op.drop_index("idx_yetai_hits_result", table_name="pred_yetai_hits")
    op.drop_index("idx_yetai_hits_sport_date", table_name="pred_yetai_hits")
    op.drop_table("pred_yetai_hits")
