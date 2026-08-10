"""NFL anytime TD predictions, actuals, and defense scheme tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260810_nfl_anytime_td"
down_revision: Union[str, None] = "20260810_nfl_game_projections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_index(table: str, index_name: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return index_name in {idx["name"] for idx in insp.get_indexes(table)}


def upgrade() -> None:
    if not _has_table("pred_nfl_defense_scheme"):
        op.create_table(
            "pred_nfl_defense_scheme",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=True),
            sa.Column("cover_base", sa.Integer(), nullable=True),
            sa.Column("man_zone_lean", sa.Float(), nullable=True),
            sa.Column("pressure_lean", sa.Float(), nullable=True),
            sa.Column("source", sa.String(50), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "team_name",
                "season",
                "week",
                name="unique_nfl_defense_scheme",
            ),
        )
    if not _has_index("pred_nfl_defense_scheme", "idx_nfl_defense_scheme_season"):
        op.create_index(
            "idx_nfl_defense_scheme_season",
            "pred_nfl_defense_scheme",
            ["season"],
        )

    if not _has_table("pred_nfl_anytime_td_predictions"):
        op.create_table(
            "pred_nfl_anytime_td_predictions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_id", sa.String(20), nullable=False),
            sa.Column("player_name", sa.String(100), nullable=False),
            sa.Column("position", sa.String(10), nullable=False),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("opponent_team_name", sa.String(100), nullable=False),
            sa.Column("expected_tds", sa.Float(), nullable=False),
            sa.Column("td_probability", sa.Float(), nullable=False),
            sa.Column("market_odds", sa.Integer(), nullable=True),
            sa.Column("market_implied_prob", sa.Float(), nullable=True),
            sa.Column("edge", sa.Float(), nullable=True),
            sa.Column("recommendation", sa.String(20), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("features", sa.JSON(), nullable=True),
            sa.Column("model_version", sa.String(20), nullable=True),
            sa.Column("prediction_date", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "season",
                "week",
                "player_id",
                name="unique_nfl_anytime_td_prediction",
            ),
        )
    if not _has_index(
        "pred_nfl_anytime_td_predictions", "idx_nfl_anytime_td_predictions_prob"
    ):
        op.create_index(
            "idx_nfl_anytime_td_predictions_prob",
            "pred_nfl_anytime_td_predictions",
            ["td_probability"],
        )
    if not _has_index(
        "pred_nfl_anytime_td_predictions", "idx_nfl_anytime_td_predictions_edge"
    ):
        op.create_index(
            "idx_nfl_anytime_td_predictions_edge",
            "pred_nfl_anytime_td_predictions",
            ["edge"],
        )
    if not _has_index(
        "pred_nfl_anytime_td_predictions", "idx_nfl_anytime_td_predictions_date"
    ):
        op.create_index(
            "idx_nfl_anytime_td_predictions_date",
            "pred_nfl_anytime_td_predictions",
            ["game_date"],
        )

    if not _has_table("pred_nfl_anytime_td_actuals"):
        op.create_table(
            "pred_nfl_anytime_td_actuals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("season", sa.Integer(), nullable=False),
            sa.Column("week", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_id", sa.String(20), nullable=False),
            sa.Column("player_name", sa.String(100), nullable=False),
            sa.Column("position", sa.String(10), nullable=False),
            sa.Column("team_name", sa.String(100), nullable=False),
            sa.Column("opponent_team_name", sa.String(100), nullable=False),
            sa.Column("scored_anytime_td", sa.Boolean(), nullable=False),
            sa.Column("actual_td_count", sa.Integer(), nullable=False),
            sa.Column("predicted_td_probability", sa.Float(), nullable=True),
            sa.Column("expected_tds", sa.Float(), nullable=True),
            sa.Column("correct_prediction", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "season",
                "week",
                "player_id",
                name="unique_nfl_anytime_td_actual",
            ),
        )
    if not _has_index("pred_nfl_anytime_td_actuals", "idx_nfl_anytime_td_actuals_date"):
        op.create_index(
            "idx_nfl_anytime_td_actuals_date",
            "pred_nfl_anytime_td_actuals",
            ["game_date"],
        )


def downgrade() -> None:
    if _has_index("pred_nfl_anytime_td_actuals", "idx_nfl_anytime_td_actuals_date"):
        op.drop_index(
            "idx_nfl_anytime_td_actuals_date",
            table_name="pred_nfl_anytime_td_actuals",
        )
    if _has_table("pred_nfl_anytime_td_actuals"):
        op.drop_table("pred_nfl_anytime_td_actuals")

    if _has_index(
        "pred_nfl_anytime_td_predictions",
        "idx_nfl_anytime_td_predictions_date",
    ):
        op.drop_index(
            "idx_nfl_anytime_td_predictions_date",
            table_name="pred_nfl_anytime_td_predictions",
        )
    if _has_index(
        "pred_nfl_anytime_td_predictions", "idx_nfl_anytime_td_predictions_edge"
    ):
        op.drop_index(
            "idx_nfl_anytime_td_predictions_edge",
            table_name="pred_nfl_anytime_td_predictions",
        )
    if _has_index(
        "pred_nfl_anytime_td_predictions", "idx_nfl_anytime_td_predictions_prob"
    ):
        op.drop_index(
            "idx_nfl_anytime_td_predictions_prob",
            table_name="pred_nfl_anytime_td_predictions",
        )
    if _has_table("pred_nfl_anytime_td_predictions"):
        op.drop_table("pred_nfl_anytime_td_predictions")

    if _has_index("pred_nfl_defense_scheme", "idx_nfl_defense_scheme_season"):
        op.drop_index(
            "idx_nfl_defense_scheme_season", table_name="pred_nfl_defense_scheme"
        )
    if _has_table("pred_nfl_defense_scheme"):
        op.drop_table("pred_nfl_defense_scheme")
