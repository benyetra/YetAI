"""Add strikeout pick metadata columns for YetAI picks and auto-pick.

Revision ID: 20260524_strikeout_pick
Revises: 2026_05_23_psc
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260524_strikeout_pick"
down_revision = "2026_05_23_psc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pred_strikeout_projections",
        sa.Column("ev_over_under", sa.String(length=7), nullable=True),
    )
    op.add_column(
        "pred_strikeout_projections",
        sa.Column("k_edge", sa.Float(), nullable=True),
    )
    op.add_column(
        "pred_strikeout_projections",
        sa.Column("pick_confidence", sa.Float(), nullable=True),
    )
    op.add_column("pred_pitcher", sa.Column("prob_over", sa.Float(), nullable=True))
    op.add_column("pred_pitcher", sa.Column("pick_edge_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("pred_pitcher", "pick_edge_pct")
    op.drop_column("pred_pitcher", "prob_over")
    op.drop_column("pred_strikeout_projections", "pick_confidence")
    op.drop_column("pred_strikeout_projections", "k_edge")
    op.drop_column("pred_strikeout_projections", "ev_over_under")
