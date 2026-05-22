"""add NBA spread projection tables

Revision ID: c3b8a1f92d04
Revises: f8a2c91e04bd
Create Date: 2026-05-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3b8a1f92d04"
down_revision: Union[str, None] = "f8a2c91e04bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pred_nba_spread_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=True),
        sa.Column("away_team_id", sa.Integer(), nullable=True),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("projected_margin", sa.Float(), nullable=False),
        sa.Column("home_win_prob", sa.Float(), nullable=False),
        sa.Column("home_elo", sa.Float(), nullable=True),
        sa.Column("away_elo", sa.Float(), nullable=True),
        sa.Column("home_court_advantage", sa.Float(), nullable=True),
        sa.Column("pace_adjustment", sa.Float(), nullable=True),
        sa.Column("market_spread_home", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(20), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("factors", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "game_date",
            "home_team_name",
            "away_team_name",
            name="unique_nba_spread_projection",
        ),
    )
    op.create_index(
        "idx_nba_spread_projections_date",
        "pred_nba_spread_projections",
        ["game_date"],
    )
    op.create_index(
        "idx_nba_spread_projections_edge",
        "pred_nba_spread_projections",
        ["edge"],
    )

    op.create_table(
        "pred_nba_spread_actuals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("actual_margin", sa.Integer(), nullable=False),
        sa.Column("home_won", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "game_date",
            "home_team_name",
            "away_team_name",
            name="unique_nba_spread_actual",
        ),
    )
    op.create_index(
        "idx_nba_spread_actuals_date", "pred_nba_spread_actuals", ["game_date"]
    )

    op.create_table(
        "pred_nba_spread_accuracy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date_range_start", sa.Date(), nullable=False),
        sa.Column("date_range_end", sa.Date(), nullable=False),
        sa.Column("total_games", sa.Integer(), nullable=False),
        sa.Column("spread_mae", sa.Float(), nullable=True),
        sa.Column("ats_hit_rate", sa.Float(), nullable=True),
        sa.Column("win_prob_brier_score", sa.Float(), nullable=True),
        sa.Column("calibration_buckets", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pred_nba_spread_accuracy")
    op.drop_index("idx_nba_spread_actuals_date", table_name="pred_nba_spread_actuals")
    op.drop_table("pred_nba_spread_actuals")
    op.drop_index(
        "idx_nba_spread_projections_edge", table_name="pred_nba_spread_projections"
    )
    op.drop_index(
        "idx_nba_spread_projections_date", table_name="pred_nba_spread_projections"
    )
    op.drop_table("pred_nba_spread_projections")
