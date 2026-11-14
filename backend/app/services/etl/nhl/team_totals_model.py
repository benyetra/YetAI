"""
NHL Team Total Goals Prediction Model

The formula the 2026-27 backtest supports (scripts/nhl_backtest_2026.py, 311
games): per-team goals rates already shrunk (K=40 toward last season) —
MAE 1.806, corr 0.134 (old model 1.853 / -0.03; league mean 1.817). Home ice,
power play / penalty kill, pace and rest terms never helped and are dropped.

    home = GF_home * GA_away / L,  away = GF_away * GA_home / L,  total = home + away

with L the league goals per team-game.
"""

from datetime import date

from app.services.etl.nhl._config import DEFAULT_GOALS_FOR_PER_GAME, _league_average
from app.services.etl.nhl._db import db_session
from app.models.predictions_models import NHLTeamStats


def _confidence(min_games):
    """Sample-size ladder on the thinner team's current-season games."""
    for floor, value in (
        (50, 85),
        (40, 80),
        (30, 75),
        (20, 70),
        (15, 68),
        (10, 65),
        (5, 60),
    ):
        if min_games >= floor:
            return value
    return 55


def predict_team_total_goals(home_team_id, away_team_id, game_date=None):
    """Predict total goals for a game; team rows are looked up by team_id."""
    home = db_session.query(NHLTeamStats).filter_by(team_id=home_team_id).first()
    away = db_session.query(NHLTeamStats).filter_by(team_id=away_team_id).first()
    for team in (home, away):
        if (
            team is None
            or not team.games_played
            or team.goals_for_per_game is None
            or team.goals_against_per_game is None
        ):
            return {"error": "Team not found or has no current-season games"}

    league = _league_average("goals_for_per_game", DEFAULT_GOALS_FOR_PER_GAME)
    home_goals = home.goals_for_per_game * away.goals_against_per_game / league
    away_goals = away.goals_for_per_game * home.goals_against_per_game / league
    total = home_goals + away_goals

    return {
        "game_date": game_date or date.today(),
        "home_team": home.team_name,
        "away_team": away.team_name,
        "predicted_total_goals": round(total, 2),
        "predicted_home_goals": round(home_goals, 2),
        "predicted_away_goals": round(away_goals, 2),
        "suggested_ou_line": round(total * 2) / 2,  # nearest 0.5
        "confidence": _confidence(min(home.games_played, away.games_played)),
        "league_goals_per_game": round(league, 3),
        "home_offense_rating": round(home.goals_for_per_game, 2),
        "away_offense_rating": round(away.goals_for_per_game, 2),
        "home_defense_rating": round(home.goals_against_per_game, 2),
        "away_defense_rating": round(away.goals_against_per_game, 2),
    }
