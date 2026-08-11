"""Tests for NFL kicker blend walk-forward, distance imputation, and volume model."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.etl.nfl.kicker_blend_tune import (
    impute_kick_distance,
    walk_forward_blend_weight,
)
from app.services.etl.nfl.ml_kicker_ensemble import (
    blend_field_goal_projection,
    estimate_ml_field_goal_volume,
)


def test_impute_kick_distance_from_kicker_avg():
    dist = impute_kick_distance({"name": "J.Smith", "avg_distance": 42.5}, {})
    assert dist == 42.5


def test_impute_kick_distance_from_game_context():
    dist = impute_kick_distance(
        {"name": "J.Smith"},
        {},
        game_context={"kick_distance": 48.0},
    )
    assert dist == 48.0


def test_walk_forward_prefers_ml_when_ml_closer():
    records = []
    for i in range(12):
        records.append(
            {
                "statistical_fgs": 1.5,
                "ml_fgs": 2.0,
                "actual_fg_made": 2.0,
            }
        )
    w = walk_forward_blend_weight(records, weight_grid=[0.0, 0.35, 0.7])
    assert w >= 0.35


def test_walk_forward_prefers_stat_when_stat_closer():
    records = []
    for i in range(12):
        records.append(
            {
                "statistical_fgs": 2.0,
                "ml_fgs": 1.0,
                "actual_fg_made": 2.0,
            }
        )
    w = walk_forward_blend_weight(records, weight_grid=[0.0, 0.35, 0.7])
    assert w <= 0.35


def test_estimate_ml_volume_is_attempts_times_make_prob():
    made, attempts = estimate_ml_field_goal_volume(0.8, predicted_attempts=2.0)
    assert attempts == 2.0
    assert made == 1.6


def test_estimate_ml_volume_uses_statistical_attempts_when_missing():
    with patch(
        "app.services.etl.nfl.statistical_kicker_prediction.get_statistical_predictor"
    ) as get_pred:
        pred = MagicMock()
        pred.estimate_field_goal_attempts.return_value = 2.2
        get_pred.return_value = pred
        made, attempts = estimate_ml_field_goal_volume(0.5, team_data={"x": 1})
    assert attempts == 2.2
    assert made == 1.1


def test_blend_uses_volume_model_not_linear_map(monkeypatch):
    monkeypatch.setenv("NFL_KICKER_ML_BLEND_WEIGHT", "1.0")
    monkeypatch.delenv("NFL_KICKER_BLEND_TUNED_WEIGHT", raising=False)

    ensemble = MagicMock()
    ensemble.available = True
    ensemble.model_source = "test"
    ensemble.predict_success_probability.return_value = 0.9

    with patch(
        "app.services.etl.nfl.ml_kicker_ensemble.get_ml_kicker_ensemble",
        return_value=ensemble,
    ):
        with patch(
            "app.services.etl.nfl.ml_kicker_ensemble.impute_kick_distance",
            return_value=40.0,
        ):
            blended, meta = blend_field_goal_projection(
                1.5,
                {"name": "Kicker"},
                {"team_red_zone_efficiency": 55},
                game_context={"predicted_attempts": 2.0},
            )

    # attempts(2.0) * make(0.9) = 1.8 — not legacy 1.2 + 0.9*2.3 = 3.27
    assert blended == 1.8
    assert meta["volume_model"] == "attempts_x_make_prob"
    assert meta["ml_projected_attempts"] == 2.0
    assert meta["ml_projected_fgs"] == 1.8
