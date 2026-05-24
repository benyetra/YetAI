"""Smoke tests for nhl_accuracy_service.daily_accuracy."""

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


def test_returns_two_nhl_buckets():
    p = SimpleNamespace(
        goalie_id=42,
        predicted_saves=28.0,
        saves_line=27.5,
        betting_recommendation="OVER 27.5",
    )
    a = SimpleNamespace(goalie_id=42, actual_saves=30)
    db = _mock_db({"NHLGoaliePredictions": [p], "NHLGoalieActuals": [a]})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    keys = [b["key"] for b in out["buckets"]]
    assert keys == ["goalie_saves_ou", "goalie_saves_mae"]
    assert out["available"] is True
    # Pick OVER 27.5, actual 30 → correct
    ou = next(b for b in out["buckets"] if b["key"] == "goalie_saves_ou")
    assert ou["primary"] == "1/1 · 100%"


def test_pass_recommendation_drops_row_from_total():
    """A goalie with `betting_recommendation='PASS'` doesn't count for the
    O/U total — there was no call to grade — but still contributes to MAE.
    """
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
