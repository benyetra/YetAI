"""add_wnba_tables

Revision ID: 0107ad42b713
Revises: 74627d53e110
Create Date: 2026-05-21 17:02:33.975016

Creates parallel pred_wnba_* tables for Phase 1 (game lines + own totals/spread
projections + accuracy tracking) and Phase 2 (player prop projections + actuals).
All tables created up front so Phase 2 needs no additional migration.

Spec: docs/superpowers/specs/2026-05-21-wnba-support-design.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0107ad42b713'
down_revision: Union[str, Sequence[str], None] = '74627d53e110'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # ---- Phase 1 tables ----

    op.create_table(
        "pred_wnba_team_roster",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, nullable=False),
        sa.Column("player_id", sa.Integer, nullable=False),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.Column("position", sa.String, nullable=True),
    )
    op.create_index("idx_wnba_team_roster_team", "pred_wnba_team_roster", ["team_id"])

    op.create_table(
        "pred_wnba_team_offense_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, unique=True, nullable=False),
        sa.Column("team_name", sa.String(100), nullable=False),
        sa.Column("games_played", sa.Integer, nullable=True),
        sa.Column("turnovers_per_game", sa.Float, nullable=True),
        sa.Column("pace", sa.Float, nullable=True),
        sa.Column("points_per_game", sa.Float, nullable=True),
        sa.Column("assists_per_game", sa.Float, nullable=True),
        sa.Column("offensive_rebounds_per_game", sa.Float, nullable=True),
        sa.Column("field_goals_made_per_game", sa.Float, nullable=True),
        sa.Column("field_goal_percentage", sa.Float, nullable=True),
        sa.Column("three_point_percentage", sa.Float, nullable=True),
    )

    op.create_table(
        "pred_wnba_team_defense_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, unique=True, nullable=False),
        sa.Column("team_name", sa.String(100), nullable=True),
        sa.Column("points_allowed_per_game", sa.Float, nullable=True),
        sa.Column("assists_allowed_per_game", sa.Float, nullable=True),
        sa.Column("rebounds_allowed_per_game", sa.Float, nullable=True),
        sa.Column("offensive_rebounds_allowed_per_game", sa.Float, nullable=True),
        sa.Column("defensive_rebounds", sa.Float, nullable=True),
        sa.Column("field_goal_pct_allowed", sa.Float, nullable=True),
        sa.Column("three_pt_pct_allowed", sa.Float, nullable=True),
        sa.Column("three_pt_made_allowed_per_game", sa.Float, nullable=True),
        sa.Column("three_pt_attempted_allowed_per_game", sa.Float, nullable=True),
        sa.Column("free_throws_allowed_per_game", sa.Float, nullable=True),
        sa.Column("turnovers", sa.Float, nullable=True),
        sa.Column("steals", sa.Float, nullable=True),
        sa.Column("blocks", sa.Float, nullable=True),
        sa.Column("personal_fouls", sa.Float, nullable=True),
        sa.Column("pace", sa.Float, nullable=True),
        sa.Column("defensive_rating", sa.Float, nullable=True),
        sa.Column("last_updated", sa.DateTime, nullable=True),
    )

    op.create_table(
        "pred_wnba_recent_games",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("player_id", sa.Integer, nullable=False),
        sa.Column("game_date", sa.Date, nullable=False),
        sa.Column("opponent_team_id", sa.Integer, nullable=False),
        sa.Column("points", sa.Float),
        sa.Column("fg_attempts", sa.Float),
        sa.Column("fg_percentage", sa.Float),
        sa.Column("three_pt_attempts", sa.Float),
        sa.Column("three_pt_percentage", sa.Float),
        sa.Column("three_pt_made", sa.Float),
        sa.Column("ft_attempts", sa.Float),
        sa.Column("ft_percentage", sa.Float),
        sa.Column("minutes", sa.Float),
        sa.Column("field_goals_made", sa.Float),
        sa.Column("free_throws_made", sa.Float),
        sa.Column("offensive_rebounds", sa.Float),
        sa.Column("defensive_rebounds", sa.Float),
        sa.Column("rebounds", sa.Float),
        sa.Column("assists", sa.Float),
        sa.Column("turnovers", sa.Float),
        sa.Column("steals", sa.Float),
        sa.Column("blocks", sa.Float),
        sa.Column("personal_fouls", sa.Float),
        sa.Column("home_game", sa.Boolean, nullable=True),
        sa.Column("true_shooting_percentage", sa.Float, nullable=True),
        sa.Column("usage_percentage", sa.Float, nullable=True),
        sa.Column("assist_percentage", sa.Float, nullable=True),
        sa.Column("effective_field_goal_percentage", sa.Float, nullable=True),
        sa.Column("pace", sa.Float, nullable=True),
        sa.Column("possessions", sa.Float, nullable=True),
        sa.Column("plus_minus", sa.Float, nullable=True),
        sa.Column("defensive_rating", sa.Float, nullable=True),
        sa.Column("offensive_rating", sa.Float, nullable=True),
        sa.Column("net_rating", sa.Float, nullable=True),
        sa.UniqueConstraint("player_id", "game_date", name="unique_wnba_recent_games_player_game_date"),
    )

    op.create_table(
        "pred_wnba_player_injury_status",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("player_id", sa.Integer, nullable=False, index=True),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="healthy"),
        sa.Column("injury_type", sa.String(100), nullable=True),
        sa.Column("games_missed", sa.Integer, server_default="0"),
        sa.Column("last_game_date", sa.Date, nullable=True),
        sa.Column("expected_return_date", sa.Date, nullable=True),
        sa.Column("date_updated", sa.DateTime, nullable=False),
        sa.Column("date_injured", sa.Date, nullable=True),
        sa.UniqueConstraint("player_id", name="unique_wnba_player_injury"),
    )

    op.create_table(
        "pred_wnba_game_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_date", sa.Date, nullable=False, index=True),
        sa.Column("home_team_id", sa.Integer, nullable=True),
        sa.Column("away_team_id", sa.Integer, nullable=True),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("odds_api_event_id", sa.String(100), nullable=True),
        sa.Column("game_time", sa.DateTime, nullable=True),
        # Consensus-only — no per-book rows (see spec)
        sa.Column("spread_home", sa.Float, nullable=True),
        sa.Column("spread_away", sa.Float, nullable=True),
        sa.Column("spread_home_odds", sa.Integer, nullable=True),
        sa.Column("spread_away_odds", sa.Integer, nullable=True),
        sa.Column("total", sa.Float, nullable=True),
        sa.Column("over_odds", sa.Integer, nullable=True),
        sa.Column("under_odds", sa.Integer, nullable=True),
        sa.Column("moneyline_home", sa.Integer, nullable=True),
        sa.Column("moneyline_away", sa.Integer, nullable=True),
        sa.Column("bookmaker", sa.String(50), nullable=True, server_default="consensus"),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.UniqueConstraint("game_date", "home_team_name", "away_team_name", name="unique_wnba_game_line"),
    )
    op.create_index("idx_wnba_game_lines_date", "pred_wnba_game_lines", ["game_date"])

    op.create_table(
        "pred_wnba_totals_projections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_date", sa.Date, nullable=False, index=True),
        sa.Column("home_team_id", sa.Integer, nullable=True),
        sa.Column("away_team_id", sa.Integer, nullable=True),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("projected_total", sa.Float, nullable=False),
        sa.Column("home_projected_score", sa.Float, nullable=True),
        sa.Column("away_projected_score", sa.Float, nullable=True),
        sa.Column("base_projection", sa.Float, nullable=True),
        sa.Column("expected_pace", sa.Float, nullable=True),
        sa.Column("home_offensive_rating", sa.Float, nullable=True),
        sa.Column("away_offensive_rating", sa.Float, nullable=True),
        sa.Column("home_defensive_rating", sa.Float, nullable=True),
        sa.Column("away_defensive_rating", sa.Float, nullable=True),
        sa.Column("injury_adjustment", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("rest_adjustment", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("venue_adjustment", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("form_adjustment", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("total_adjustment", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("market_total", sa.Float, nullable=True),
        sa.Column("edge", sa.Float, nullable=True),
        sa.Column("recommendation", sa.String(20), nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("injury_report", sa.JSON, nullable=True),
        sa.Column("factors", sa.JSON, nullable=True),
        sa.Column("home_starters", sa.JSON, nullable=True),
        sa.Column("away_starters", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("game_date", "home_team_name", "away_team_name", name="unique_wnba_totals_projection"),
    )
    op.create_index("idx_wnba_totals_projections_date", "pred_wnba_totals_projections", ["game_date"])
    op.create_index("idx_wnba_totals_projections_edge", "pred_wnba_totals_projections", ["edge"])

    op.create_table(
        "pred_wnba_totals_actuals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_date", sa.Date, nullable=False, index=True),
        sa.Column("home_team_id", sa.Integer, nullable=True),
        sa.Column("away_team_id", sa.Integer, nullable=True),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("home_score", sa.Integer, nullable=False),
        sa.Column("away_score", sa.Integer, nullable=False),
        sa.Column("actual_total", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("game_date", "home_team_name", "away_team_name", name="unique_wnba_totals_actual"),
    )

    op.create_table(
        "pred_wnba_team_pace_efficiency",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("team_id", sa.Integer, nullable=False),
        sa.Column("team_name", sa.String(100), nullable=False),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("pace", sa.Float, nullable=True),
        sa.Column("pace_rank", sa.Integer, nullable=True),
        sa.Column("pace_l5", sa.Float, nullable=True),
        sa.Column("pace_l10", sa.Float, nullable=True),
        sa.Column("home_pace", sa.Float, nullable=True),
        sa.Column("away_pace", sa.Float, nullable=True),
        sa.Column("offensive_rating", sa.Float, nullable=True),
        sa.Column("offensive_rating_rank", sa.Integer, nullable=True),
        sa.Column("offensive_rating_l5", sa.Float, nullable=True),
        sa.Column("offensive_rating_l10", sa.Float, nullable=True),
        sa.Column("points_per_game", sa.Float, nullable=True),
        sa.Column("defensive_rating", sa.Float, nullable=True),
        sa.Column("defensive_rating_rank", sa.Integer, nullable=True),
        sa.Column("defensive_rating_l5", sa.Float, nullable=True),
        sa.Column("defensive_rating_l10", sa.Float, nullable=True),
        sa.Column("points_allowed_per_game", sa.Float, nullable=True),
        sa.Column("net_rating", sa.Float, nullable=True),
        sa.Column("true_shooting_pct", sa.Float, nullable=True),
        sa.Column("effective_fg_pct", sa.Float, nullable=True),
        sa.Column("three_pt_rate", sa.Float, nullable=True),
        sa.Column("three_pt_pct", sa.Float, nullable=True),
        sa.Column("free_throw_rate", sa.Float, nullable=True),
        sa.Column("avg_game_total", sa.Float, nullable=True),
        sa.Column("avg_home_total", sa.Float, nullable=True),
        sa.Column("avg_away_total", sa.Float, nullable=True),
        sa.Column("over_under_record", sa.String(20), nullable=True),
        sa.Column("games_played", sa.Integer, nullable=True),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.UniqueConstraint("team_id", "date", name="unique_wnba_team_pace_efficiency"),
    )

    op.create_table(
        "pred_wnba_totals_accuracy",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date_range_start", sa.Date, nullable=False),
        sa.Column("date_range_end", sa.Date, nullable=False),
        sa.Column("total_games", sa.Integer, nullable=False),
        sa.Column("mean_absolute_error", sa.Float, nullable=True),
        sa.Column("root_mean_square_error", sa.Float, nullable=True),
        sa.Column("directional_accuracy", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ---- Spread projection — NEW vs NBA (Phase 1 deliverable beyond NBA parity) ----

    op.create_table(
        "pred_wnba_spread_projections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_date", sa.Date, nullable=False, index=True),
        sa.Column("home_team_id", sa.Integer, nullable=True),
        sa.Column("away_team_id", sa.Integer, nullable=True),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("projected_margin", sa.Float, nullable=False),  # positive = home favored
        sa.Column("home_win_prob", sa.Float, nullable=False),
        sa.Column("home_elo", sa.Float, nullable=True),
        sa.Column("away_elo", sa.Float, nullable=True),
        sa.Column("home_court_advantage", sa.Float, nullable=True),
        sa.Column("pace_adjustment", sa.Float, nullable=True),
        sa.Column("market_spread_home", sa.Float, nullable=True),
        sa.Column("edge", sa.Float, nullable=True),  # projected_margin - (-market_spread_home)
        sa.Column("recommendation", sa.String(20), nullable=True),  # HOME, AWAY, NO_PLAY
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("factors", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("game_date", "home_team_name", "away_team_name", name="unique_wnba_spread_projection"),
    )
    op.create_index("idx_wnba_spread_projections_date", "pred_wnba_spread_projections", ["game_date"])
    op.create_index("idx_wnba_spread_projections_edge", "pred_wnba_spread_projections", ["edge"])

    op.create_table(
        "pred_wnba_spread_actuals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("game_date", sa.Date, nullable=False, index=True),
        sa.Column("home_team_name", sa.String(100), nullable=False),
        sa.Column("away_team_name", sa.String(100), nullable=False),
        sa.Column("home_score", sa.Integer, nullable=False),
        sa.Column("away_score", sa.Integer, nullable=False),
        sa.Column("actual_margin", sa.Integer, nullable=False),  # home_score - away_score
        sa.Column("home_won", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("game_date", "home_team_name", "away_team_name", name="unique_wnba_spread_actual"),
    )

    op.create_table(
        "pred_wnba_spread_accuracy",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date_range_start", sa.Date, nullable=False),
        sa.Column("date_range_end", sa.Date, nullable=False),
        sa.Column("total_games", sa.Integer, nullable=False),
        sa.Column("spread_mae", sa.Float, nullable=True),
        sa.Column("ats_hit_rate", sa.Float, nullable=True),  # % picks that covered when |edge| > threshold
        sa.Column("win_prob_brier_score", sa.Float, nullable=True),
        sa.Column("calibration_buckets", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ---- Phase 2 tables (created up-front per spec; will be populated in Plan B) ----

    op.create_table(
        "pred_wnba_today_active_players",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("player_id", sa.Integer, nullable=False),
        sa.Column("player_name", sa.String(100), nullable=False),
        sa.Column("team_id", sa.Integer, nullable=False),
        sa.Column("team_name", sa.String(100), nullable=False),
        sa.Column("opponent_team_id", sa.Integer, nullable=True),
        sa.Column("opponent_team_name", sa.String(100), nullable=True),
        sa.Column("game_date", sa.Date, nullable=False, index=True),
        sa.Column("home_game", sa.Boolean, nullable=True),
        sa.Column("last_updated", sa.DateTime, nullable=False),
        sa.UniqueConstraint("player_id", "game_date", name="unique_wnba_today_active"),
    )

    for prop in ("points", "assists", "rebounds"):
        op.create_table(
            f"pred_wnba_{prop}_projections",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("date", sa.Date, nullable=False, index=True),
            sa.Column("player_id", sa.Integer, nullable=False),
            sa.Column("player_name", sa.String, nullable=True),
            sa.Column("opponent_team_name", sa.String, nullable=True),
            sa.Column(f"projected_{prop}", sa.Float, nullable=False),
            sa.Column("market_line", sa.Float, nullable=True),
            sa.Column("edge", sa.Float, nullable=True),
            sa.Column("recommendation", sa.String(20), nullable=True),
            sa.Column("confidence_score", sa.Float, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("player_id", "date", name=f"unique_wnba_{prop}_projection"),
        )
        op.create_table(
            f"pred_wnba_{prop}_actuals",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("date", sa.Date, nullable=False, index=True),
            sa.Column("player_id", sa.Integer, nullable=False),
            sa.Column("player_name", sa.String, nullable=True),
            sa.Column(f"actual_{prop}", sa.Float, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("player_id", "date", name=f"unique_wnba_{prop}_actual"),
        )


def downgrade():
    # Drop in reverse dependency order
    for prop in ("rebounds", "assists", "points"):
        op.drop_table(f"pred_wnba_{prop}_actuals")
        op.drop_table(f"pred_wnba_{prop}_projections")
    op.drop_table("pred_wnba_today_active_players")
    op.drop_table("pred_wnba_spread_accuracy")
    op.drop_table("pred_wnba_spread_actuals")
    op.drop_index("idx_wnba_spread_projections_edge", table_name="pred_wnba_spread_projections")
    op.drop_index("idx_wnba_spread_projections_date", table_name="pred_wnba_spread_projections")
    op.drop_table("pred_wnba_spread_projections")
    op.drop_table("pred_wnba_totals_accuracy")
    op.drop_table("pred_wnba_team_pace_efficiency")
    op.drop_table("pred_wnba_totals_actuals")
    op.drop_index("idx_wnba_totals_projections_edge", table_name="pred_wnba_totals_projections")
    op.drop_index("idx_wnba_totals_projections_date", table_name="pred_wnba_totals_projections")
    op.drop_table("pred_wnba_totals_projections")
    op.drop_index("idx_wnba_game_lines_date", table_name="pred_wnba_game_lines")
    op.drop_table("pred_wnba_game_lines")
    op.drop_table("pred_wnba_player_injury_status")
    op.drop_table("pred_wnba_recent_games")
    op.drop_table("pred_wnba_team_defense_stats")
    op.drop_table("pred_wnba_team_offense_stats")
    op.drop_index("idx_wnba_team_roster_team", table_name="pred_wnba_team_roster")
    op.drop_table("pred_wnba_team_roster")
