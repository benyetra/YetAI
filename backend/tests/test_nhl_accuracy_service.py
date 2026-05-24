"""Smoke tests for nhl_accuracy_service.daily_accuracy.

Verifies plumbing of all 4 prediction types (goalies, team shots, player
shots, team totals) into the unified buckets shape.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import nhl_accuracy_service as svc


def _mock_db(rows_by_model):
    db = MagicMock()

    def side_effect(model):
        result = MagicMock()
        result.filter.return_value.all.return_value = rows_by_model.get(
            model.__name__, []
        )
        return result

    db.query.side_effect = side_effect
    return db


def test_returns_eight_nhl_buckets_in_order():
    """Goalies + team shots + player shots + team totals, each O/U then MAE."""
    today = date(2026, 5, 23)
    goalie_p = SimpleNamespace(
        goalie_id=42,
        predicted_saves=28.0,
        saves_line=27.5,
        betting_recommendation="OVER 27.5",
    )
    goalie_a = SimpleNamespace(goalie_id=42, actual_saves=30)
    team_shots_p = SimpleNamespace(
        team_name="Bruins",
        game_date=today,
        predicted_shots=30.0,
        shots_line=29.5,
        betting_recommendation="OVER 29.5",
    )
    team_shots_a = SimpleNamespace(
        team_name="Bruins",
        game_date=today,
        actual_shots=33,
    )
    player_p = SimpleNamespace(
        player_id=99,
        predicted_shots=3.5,
        shots_line=2.5,
        betting_recommendation="OVER 2.5",
    )
    player_a = SimpleNamespace(player_id=99, actual_shots=4)
    totals_p = SimpleNamespace(
        home_team_name="Rangers",
        away_team_name="Bruins",
        predicted_total_goals=6.0,
        draftkings_ou_line=5.5,
        betting_recommendation="OVER 5.5",
    )
    totals_a = SimpleNamespace(
        home_team_name="Rangers",
        away_team_name="Bruins",
        actual_total_goals=6,
    )
    db = _mock_db(
        {
            "NHLGoaliePredictions": [goalie_p],
            "NHLGoalieActuals": [goalie_a],
            "NHLTeamShotsPredictions": [team_shots_p],
            "NHLTeamShotsActuals": [team_shots_a],
            "NHLPlayerShotsPredictions": [player_p],
            "NHLPlayerShotsActuals": [player_a],
            "NHLTeamTotalsPredictions": [totals_p],
            "NHLTeamTotalsActuals": [totals_a],
        }
    )
    out = svc.daily_accuracy(db, target_date=today)
    keys = [b["key"] for b in out["buckets"]]
    assert keys == [
        "goalie_saves_ou",
        "goalie_saves_mae",
        "team_shots_ou",
        "team_shots_mae",
        "player_shots_ou",
        "player_shots_mae",
        "team_totals_ou",
        "team_totals_mae",
    ]
    # All four O/U picks won (over X, actual > X). Spot-check team_shots.
    ts = next(b for b in out["buckets"] if b["key"] == "team_shots_ou")
    assert ts["primary"] == "1/1 · 100%"
    # totals: actual 6 vs line 5.5 → over wins
    tt = next(b for b in out["buckets"] if b["key"] == "team_totals_ou")
    assert tt["primary"] == "1/1 · 100%"


def test_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    # All 8 buckets still emitted (with 0/0 entries); UI hides via `available`.
    assert len(out["buckets"]) == 8


def test_pass_recommendation_drops_row_from_ou_total():
    """Predictions tagged PASS don't count for or against the O/U total
    but still contribute to MAE on the prediction type."""
    p = SimpleNamespace(
        goalie_id=42,
        predicted_saves=28.0,
        saves_line=27.5,
        betting_recommendation="PASS",
    )
    a = SimpleNamespace(goalie_id=42, actual_saves=30)
    db = _mock_db({"NHLGoaliePredictions": [p], "NHLGoalieActuals": [a]})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    ou = next(b for b in out["buckets"] if b["key"] == "goalie_saves_ou")
    assert ou["primary"] == "0/0 · —"
    mae = next(b for b in out["buckets"] if b["key"] == "goalie_saves_mae")
    assert "MAE 2.00" in mae["primary"]
