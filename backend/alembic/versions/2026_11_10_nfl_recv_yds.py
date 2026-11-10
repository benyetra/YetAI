"""NFL receiving yards predictions + actuals tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261110_nfl_recv_yds"
down_revision: Union[str, None] = "20260911_password_set"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("pred_recv_yds_predictions"):
        op.create_table(
            "pred_recv_yds_predictions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_id", sa.String(20), nullable=False),
            sa.Column("player_name", sa.String(100), nullable=False),
            sa.Column("position", sa.String(10), nullable=False),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("opponent_team_name", sa.String(100), nullable=False),
            sa.Column("predicted_receiving_yards", sa.Float(), nullable=False),
            sa.Column("model_yards", sa.Float(), nullable=True),
            sa.Column("ou_line", sa.Float(), nullable=True),
            sa.Column("over_odds", sa.Integer(), nullable=True),
            sa.Column("under_odds", sa.Integer(), nullable=True),
            sa.Column("best_over_book", sa.String(50), nullable=True),
            sa.Column("best_under_book", sa.String(50), nullable=True),
            sa.Column("edge", sa.Float(), nullable=True),
            sa.Column("edge_percentage", sa.Float(), nullable=True),
            sa.Column("betting_recommendation", sa.String(20), nullable=True),
            sa.Column("bet_size", sa.String(10), nullable=True),
            sa.Column("recommendation_reason", sa.String(200), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("prediction_method", sa.String(50), nullable=True),
            sa.Column("features", sa.JSON(), nullable=True),
            sa.Column("model_version", sa.String(64), nullable=True),
            sa.Column("prediction_date", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "season",
                "week",
                "player_id",
                name="unique_nfl_recv_yds_prediction",
            ),
        )
        op.create_index(
            "idx_nfl_recv_yds_predictions_date",
            "pred_recv_yds_predictions",
            ["game_date"],
        )
        op.create_index(
            "idx_nfl_recv_yds_predictions_edge",
            "pred_recv_yds_predictions",
            ["edge"],
        )
        op.create_index(
            "idx_nfl_recv_yds_predictions_pos",
            "pred_recv_yds_predictions",
            ["position"],
        )

    if not _has_table("pred_recv_yds_actuals"):
        op.create_table(
            "pred_recv_yds_actuals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_id", sa.String(20), nullable=False),
            sa.Column("player_name", sa.String(100), nullable=False),
            sa.Column("position", sa.String(10), nullable=False),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("opponent_team_name", sa.String(100), nullable=False),
            sa.Column("actual_receiving_yards", sa.Float(), nullable=False),
            sa.Column("actual_receptions", sa.Integer(), nullable=True),
            sa.Column("actual_targets", sa.Integer(), nullable=True),
            sa.Column("predicted_receiving_yards", sa.Float(), nullable=True),
            sa.Column("ou_line", sa.Float(), nullable=True),
            sa.Column("prediction_error", sa.Float(), nullable=True),
            sa.Column("hit_over_under", sa.Boolean(), nullable=True),
            sa.Column("prediction_method", sa.String(50), nullable=True),
            sa.Column("data_collection_date", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "season",
                "week",
                "player_id",
                name="unique_nfl_recv_yds_actual",
            ),
        )
        op.create_index(
            "idx_nfl_recv_yds_actuals_date",
            "pred_recv_yds_actuals",
            ["game_date"],
        )


def downgrade() -> None:
    if _has_table("pred_recv_yds_actuals"):
        op.drop_table("pred_recv_yds_actuals")
    if _has_table("pred_recv_yds_predictions"):
        op.drop_table("pred_recv_yds_predictions")
