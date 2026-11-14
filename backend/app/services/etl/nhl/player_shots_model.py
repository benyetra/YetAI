"""
NHL Player Shots Prediction Model

The formula the 2026-27 backtest supports (scripts/nhl_backtest_2026.py, 7,574
skater-games): the plain shrunk shots-per-game rate (K=10) — lined MAE 1.304 vs
the line's 1.303, corr 0.300 vs 0.313 (the old multiplier stack: MAE 1.795, corr
0.123). Opponent shots allowed x home ice gained 0.0025 MAE (bootstrap 95% CI
-0.0003..0.0054, not shown to help); ice-time trend, the old bucketed ice-time
multiplier (1.350 lined) and a last-10 blend did not help. None is in the model.
"""

from datetime import date

from app.services.etl.nhl._db import db_session
from app.models.predictions_models import NHLPlayer


def predict_player_shots(
    player_id, opponent_team_id=None, is_home=True, game_date=None
):
    """Predict shots on goal: the player's stored shrunk shots_per_game."""
    player = db_session.query(NHLPlayer).filter_by(player_id=player_id).first()
    if not player:
        return {"error": "Player not found"}

    games_played = player.games_played or 0
    if games_played < 1:
        return {"error": "Player has no games this season"}
    if not player.shots_per_game:
        return {"error": "Player has no shot data"}

    shots = round(float(player.shots_per_game), 2)
    if games_played >= 40:
        confidence = 85
    elif games_played >= 20:
        confidence = 75
    elif games_played >= 10:
        confidence = 65
    else:
        confidence = 50

    return {
        "player_id": player.player_id,
        "player_name": player.name,
        "team_name": player.team_name,
        "game_date": game_date or date.today(),
        "is_home": is_home,
        "predicted_shots": shots,
        "baseline_shots": shots,
        "confidence": confidence,
        "player_toi_per_game": player.toi_per_game,
        "player_position": player.position,
        "games_played": games_played,
    }
