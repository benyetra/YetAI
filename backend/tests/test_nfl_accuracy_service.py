"""Smoke tests for nfl_accuracy_service.daily_accuracy."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import nfl_accuracy_service as svc


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


def test_returns_three_nfl_buckets():
    qb_p = SimpleNamespace(
        qb_player_id="qb1",
        predicted_passing_yards=275.0,
        ou_line=250.5,
        betting_recommendation="OVER",
    )
    qb_a = SimpleNamespace(qb_player_id="qb1", actual_passing_yards=310.0)
    k_p = SimpleNamespace(kicker_player_id="k1", predicted_fg_made=2.5)
    k_a = SimpleNamespace(kicker_id="k1", actual_field_goals_made=3)
    db = _mock_db(
        {
            "QBPredictions": [qb_p],
            "QBActuals": [qb_a],
            "KickerPredictions": [k_p],
            "KickerActuals": [k_a],
        }
    )
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    keys = [b["key"] for b in out["buckets"]]
    assert keys == ["qb_passing_ou", "qb_passing_mae", "kicker_fg_mae"]
    assert out["available"] is True
    # QB picked OVER 250.5, actual 310 → correct
    qb_ou = next(b for b in out["buckets"] if b["key"] == "qb_passing_ou")
    assert qb_ou["primary"] == "1/1 · 100%"


def test_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 3
