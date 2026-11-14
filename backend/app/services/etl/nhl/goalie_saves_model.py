"""
NHL Goalie Saves Prediction Model

The formula the 2026-27 backtest supports (scripts/nhl_backtest_2026.py, 622
starter-games, no stored lines exist): shots against = opponent shots-for per game
x the goalie's own team shots-against per game / league shots-for per game, times
the LEAGUE save percentage. MAE 5.16, corr 0.21 (full-game starters 4.67 vs 4.79
for a constant). A goalie-specific save pct did not beat the league one (5.18);
rest, momentum, venue, familiarity, workload, injury, special teams, shot quality,
vs-team history, trends and time of day showed no help and are not in the model.
"""

from app.services.etl.nhl._config import DEFAULT_SHOTS_FOR, _league_average
from app.services.etl.nhl._db import db_session
from app.models.predictions_models import NHLGoalie, NHLTeamStats

DEFAULT_LEAGUE_SAVE_PCT = 0.900


def get_league_save_pct():
    """This season's league save pct: saves / shots against over goalies with games."""
    rows = (
        db_session.query(NHLGoalie.saves, NHLGoalie.shots_against)
        .filter(NHLGoalie.games_played > 0)
        .all()
    )
    saves = sum(r[0] or 0 for r in rows)
    shots = sum(r[1] or 0 for r in rows)
    return saves / shots if shots > 0 else DEFAULT_LEAGUE_SAVE_PCT


def _confidence(games_played):
    """Sample-size ladder on the goalie's current-season games."""
    if games_played >= 40:
        return 90
    if games_played >= 30:
        return 85
    if games_played >= 20:
        return 75
    if games_played >= 10:
        return 65
    return 55


def predict_goalie_saves(
    goalie_id, goalie_name, team_id, opponent_team_id, game_date=None, is_home=None
):
    """Predict saves for a goalie; team rows are looked up by team_id."""
    team = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()
    opponent = (
        db_session.query(NHLTeamStats).filter_by(team_id=opponent_team_id).first()
    )
    if (
        team is None
        or opponent is None
        or team.shots_against_per_game is None
        or opponent.shots_for_per_game is None
    ):
        return {"error": "Team not found"}

    league_shots = _league_average("shots_for_per_game", DEFAULT_SHOTS_FOR)
    shots_against = (
        opponent.shots_for_per_game * team.shots_against_per_game / league_shots
    )
    save_pct = get_league_save_pct()

    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()
    season_sv = None
    if goalie and goalie.shots_against and goalie.saves is not None:
        season_sv = round(goalie.saves / goalie.shots_against, 3)

    return {
        "goalie_id": goalie_id,
        "goalie_name": goalie_name,
        "game_date": game_date,
        "predicted_saves": round(shots_against * save_pct, 2),
        "predicted_shots_against": shots_against,
        "predicted_save_pct": save_pct,
        "confidence": _confidence((goalie.games_played or 0) if goalie else 0),
        "goalie_season_sv_pct": season_sv,
        "opponent_shots_avg": opponent.shots_for_per_game,
        "is_home": is_home,
    }
