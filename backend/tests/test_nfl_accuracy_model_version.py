"""Extra accuracy service checks for model_version breakdown."""

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


def test_by_model_version_breakdown():
    qb_p = SimpleNamespace(
        qb_player_id="qb1",
        predicted_passing_yards=275.0,
        ou_line=250.5,
        betting_recommendation="OVER",
        model_version="tier-v3",
    )
    qb_a = SimpleNamespace(qb_player_id="qb1", actual_passing_yards=310.0)
    k_p = SimpleNamespace(
        kicker_player_id="k1",
        predicted_fg_made=2.5,
        model_version="kicker-blend-v2",
    )
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
    assert "by_model_version" in out
    assert out["by_model_version"]["qb_passing_mae"]["tier-v3"]["n"] == 1
    assert out["by_model_version"]["kicker_fg_mae"]["kicker-blend-v2"]["n"] == 1


def test_mae_by_model_version_helper():
    rows = [
        {
            "predicted_passing_yards": 250,
            "actual_passing_yards": 260,
            "model_version": "tier-v3",
        },
        {
            "predicted_passing_yards": 250,
            "actual_passing_yards": 240,
            "model_version": "tier-v3",
        },
        {
            "predicted_passing_yards": 200,
            "actual_passing_yards": 230,
            "model_version": "gbm-qb-yards-20260811",
        },
    ]
    out = svc.mae_by_model_version(
        rows,
        projected_field="predicted_passing_yards",
        actual_field="actual_passing_yards",
    )
    assert out["tier-v3"]["mae"] == 10.0
    assert out["gbm-qb-yards-20260811"]["mae"] == 30.0
