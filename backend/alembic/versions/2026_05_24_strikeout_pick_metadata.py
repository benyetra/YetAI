"""Add strikeout pick metadata columns for YetAI picks and auto-pick.

Revision ID: 20260524_strikeout_pick
Revises: 2026_05_23_psc
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260524_strikeout_pick"
down_revision = "2026_05_23_psc"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pred_strikeout_projections", "ev_over_under"):
        op.add_column(
            "pred_strikeout_projections",
            sa.Column("ev_over_under", sa.String(length=7), nullable=True),
        )
    if not _has_column("pred_strikeout_projections", "k_edge"):
        op.add_column(
            "pred_strikeout_projections",
            sa.Column("k_edge", sa.Float(), nullable=True),
        )
    if not _has_column("pred_strikeout_projections", "pick_confidence"):
        op.add_column(
            "pred_strikeout_projections",
            sa.Column("pick_confidence", sa.Float(), nullable=True),
        )
    if not _has_column("pred_pitcher", "prob_over"):
        op.add_column("pred_pitcher", sa.Column("prob_over", sa.Float(), nullable=True))
    if not _has_column("pred_pitcher", "pick_edge_pct"):
        op.add_column(
            "pred_pitcher", sa.Column("pick_edge_pct", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    if _has_column("pred_pitcher", "pick_edge_pct"):
        op.drop_column("pred_pitcher", "pick_edge_pct")
    if _has_column("pred_pitcher", "prob_over"):
        op.drop_column("pred_pitcher", "prob_over")
    if _has_column("pred_strikeout_projections", "pick_confidence"):
        op.drop_column("pred_strikeout_projections", "pick_confidence")
    if _has_column("pred_strikeout_projections", "k_edge"):
        op.drop_column("pred_strikeout_projections", "k_edge")
    if _has_column("pred_strikeout_projections", "ev_over_under"):
        op.drop_column("pred_strikeout_projections", "ev_over_under")
