"""NFL game lines, spread/totals projections, actuals, and team Elo tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260810_nfl_game_projections"
down_revision: Union[str, None] = "20260807_lv_draft_lottery"
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
    if not _has_table("pred_nfl_game_lines"):
        op.create_table(
            "pred_nfl_game_lines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("home_team_id", sa.Integer(), nullable=True),
            sa.Column("away_team_id", sa.Integer(), nullable=True),
            sa.Column("home_team_name", sa.String(100), nullable=False),
            sa.Column("away_team_name", sa.String(100), nullable=False),
            sa.Column("odds_api_event_id", sa.String(100), nullable=True),
            sa.Column("game_time", sa.DateTime(), nullable=True),
            sa.Column("spread_home", sa.Float(), nullable=True),
            sa.Column("spread_away", sa.Float(), nullable=True),
            sa.Column("spread_home_odds", sa.Integer(), nullable=True),
            sa.Column("spread_away_odds", sa.Integer(), nullable=True),
            sa.Column("total", sa.Float(), nullable=True),
            sa.Column("over_odds", sa.Integer(), nullable=True),
            sa.Column("under_odds", sa.Integer(), nullable=True),
            sa.Column("moneyline_home", sa.Integer(), nullable=True),
            sa.Column("moneyline_away", sa.Integer(), nullable=True),
            sa.Column("bookmaker", sa.String(50), nullable=True),
            sa.Column("last_updated", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "game_date",
                "home_team_name",
                "away_team_name",
                name="unique_nfl_game_line",
            ),
        )
    if not _has_index("pred_nfl_game_lines", "idx_nfl_game_lines_date"):
        op.create_index("idx_nfl_game_lines_date", "pred_nfl_game_lines", ["game_date"])

    if not _has_table("pred_nfl_spread_projections"):
        op.create_table(
            "pred_nfl_spread_projections",
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
                name="unique_nfl_spread_projection",
            ),
        )
    if not _has_index("pred_nfl_spread_projections", "idx_nfl_spread_projections_date"):
        op.create_index(
            "idx_nfl_spread_projections_date",
            "pred_nfl_spread_projections",
            ["game_date"],
        )
    if not _has_index("pred_nfl_spread_projections", "idx_nfl_spread_projections_edge"):
        op.create_index(
            "idx_nfl_spread_projections_edge",
            "pred_nfl_spread_projections",
            ["edge"],
        )

    if not _has_table("pred_nfl_totals_projections"):
        op.create_table(
            "pred_nfl_totals_projections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("home_team_id", sa.Integer(), nullable=True),
            sa.Column("away_team_id", sa.Integer(), nullable=True),
            sa.Column("home_team_name", sa.String(100), nullable=False),
            sa.Column("away_team_name", sa.String(100), nullable=False),
            sa.Column("projected_total", sa.Float(), nullable=False),
            sa.Column("home_projected_score", sa.Float(), nullable=True),
            sa.Column("away_projected_score", sa.Float(), nullable=True),
            sa.Column("base_projection", sa.Float(), nullable=True),
            sa.Column("expected_pace", sa.Float(), nullable=True),
            sa.Column("home_offensive_rating", sa.Float(), nullable=True),
            sa.Column("away_offensive_rating", sa.Float(), nullable=True),
            sa.Column("home_defensive_rating", sa.Float(), nullable=True),
            sa.Column("away_defensive_rating", sa.Float(), nullable=True),
            sa.Column("injury_adjustment", sa.Float(), nullable=True),
            sa.Column("rest_adjustment", sa.Float(), nullable=True),
            sa.Column("venue_adjustment", sa.Float(), nullable=True),
            sa.Column("form_adjustment", sa.Float(), nullable=True),
            sa.Column("total_adjustment", sa.Float(), nullable=True),
            sa.Column("market_total", sa.Float(), nullable=True),
            sa.Column("edge", sa.Float(), nullable=True),
            sa.Column("recommendation", sa.String(20), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("injury_report", sa.JSON(), nullable=True),
            sa.Column("factors", sa.JSON(), nullable=True),
            sa.Column("home_starters", sa.JSON(), nullable=True),
            sa.Column("away_starters", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "game_date",
                "home_team_name",
                "away_team_name",
                name="unique_nfl_totals_projection",
            ),
        )
    if not _has_index("pred_nfl_totals_projections", "idx_nfl_totals_projections_date"):
        op.create_index(
            "idx_nfl_totals_projections_date",
            "pred_nfl_totals_projections",
            ["game_date"],
        )
    if not _has_index("pred_nfl_totals_projections", "idx_nfl_totals_projections_edge"):
        op.create_index(
            "idx_nfl_totals_projections_edge",
            "pred_nfl_totals_projections",
            ["edge"],
        )

    if not _has_table("pred_nfl_spread_actuals"):
        op.create_table(
            "pred_nfl_spread_actuals",
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
                name="unique_nfl_spread_actual",
            ),
        )

    if not _has_table("pred_nfl_totals_actuals"):
        op.create_table(
            "pred_nfl_totals_actuals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("home_team_id", sa.Integer(), nullable=True),
            sa.Column("away_team_id", sa.Integer(), nullable=True),
            sa.Column("home_team_name", sa.String(100), nullable=False),
            sa.Column("away_team_name", sa.String(100), nullable=False),
            sa.Column("actual_total", sa.Integer(), nullable=False),
            sa.Column("home_actual_score", sa.Integer(), nullable=True),
            sa.Column("away_actual_score", sa.Integer(), nullable=True),
            sa.Column("projected_total", sa.Float(), nullable=True),
            sa.Column("market_total", sa.Float(), nullable=True),
            sa.Column("projection_error", sa.Float(), nullable=True),
            sa.Column("market_error", sa.Float(), nullable=True),
            sa.Column("was_over", sa.Boolean(), nullable=True),
            sa.Column("correct_prediction", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "game_date",
                "home_team_name",
                "away_team_name",
                name="unique_nfl_totals_actual",
            ),
        )
    if not _has_index("pred_nfl_totals_actuals", "idx_nfl_totals_actuals_date"):
        op.create_index(
            "idx_nfl_totals_actuals_date", "pred_nfl_totals_actuals", ["game_date"]
        )

    if not _has_table("pred_nfl_team_elo"):
        op.create_table(
            "pred_nfl_team_elo",
            sa.Column("team_name", sa.String(100), primary_key=True),
            sa.Column("elo", sa.Float(), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    if _has_table("pred_nfl_team_elo"):
        op.drop_table("pred_nfl_team_elo")

    if _has_index("pred_nfl_totals_actuals", "idx_nfl_totals_actuals_date"):
        op.drop_index(
            "idx_nfl_totals_actuals_date", table_name="pred_nfl_totals_actuals"
        )
    if _has_table("pred_nfl_totals_actuals"):
        op.drop_table("pred_nfl_totals_actuals")

    if _has_table("pred_nfl_spread_actuals"):
        op.drop_table("pred_nfl_spread_actuals")

    if _has_index("pred_nfl_totals_projections", "idx_nfl_totals_projections_edge"):
        op.drop_index(
            "idx_nfl_totals_projections_edge",
            table_name="pred_nfl_totals_projections",
        )
    if _has_index("pred_nfl_totals_projections", "idx_nfl_totals_projections_date"):
        op.drop_index(
            "idx_nfl_totals_projections_date",
            table_name="pred_nfl_totals_projections",
        )
    if _has_table("pred_nfl_totals_projections"):
        op.drop_table("pred_nfl_totals_projections")

    if _has_index("pred_nfl_spread_projections", "idx_nfl_spread_projections_edge"):
        op.drop_index(
            "idx_nfl_spread_projections_edge",
            table_name="pred_nfl_spread_projections",
        )
    if _has_index("pred_nfl_spread_projections", "idx_nfl_spread_projections_date"):
        op.drop_index(
            "idx_nfl_spread_projections_date",
            table_name="pred_nfl_spread_projections",
        )
    if _has_table("pred_nfl_spread_projections"):
        op.drop_table("pred_nfl_spread_projections")

    if _has_index("pred_nfl_game_lines", "idx_nfl_game_lines_date"):
        op.drop_index("idx_nfl_game_lines_date", table_name="pred_nfl_game_lines")
    if _has_table("pred_nfl_game_lines"):
        op.drop_table("pred_nfl_game_lines")
