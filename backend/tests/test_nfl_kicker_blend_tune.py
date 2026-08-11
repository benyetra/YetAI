"""Tests for NFL kicker blend, distance mixture, and volume model."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.etl.nfl.kicker_blend_tune import (
    impute_kick_distance,
    resolve_blend_weight,
    walk_forward_blend_weight,
)
from app.services.etl.nfl.kicker_volume import (
    estimate_attempts_heuristic,
    expected_fg_made,
    mixture_make_probability,
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
    records = [
        {"statistical_fgs": 1.5, "ml_fgs": 2.0, "actual_fg_made": 2.0}
        for _ in range(12)
    ]
    w = walk_forward_blend_weight(records, weight_grid=[0.0, 0.35, 0.7])
    assert w >= 0.35


def test_walk_forward_prefers_stat_when_stat_closer():
    records = [
        {"statistical_fgs": 2.0, "ml_fgs": 1.0, "actual_fg_made": 2.0}
        for _ in range(12)
    ]
    w = walk_forward_blend_weight(records, weight_grid=[0.0, 0.35, 0.7])
    assert w <= 0.35


def test_default_blend_weight_is_30():
    assert resolve_blend_weight() == 0.30


def test_mixture_make_probability_in_band():
    p = mixture_make_probability(kicker_make_rate=0.88)
    assert 0.5 < p < 0.99


def test_estimate_attempts_heuristic_responds_to_rz():
    efficient = estimate_attempts_heuristic({"team_red_zone_efficiency": 75})
    poor = estimate_attempts_heuristic({"team_red_zone_efficiency": 45})
    assert poor > efficient


def test_expected_fg_made_is_attempts_times_make():
    made, meta = expected_fg_made(
        attempts=2.0, make_prob=0.8, classifier_make_prob=None
    )
    assert made == 1.6
    assert meta["volume_model"] == "attempts_x_distance_mixture"


def test_estimate_ml_volume_blends_classifier():
    made, attempts = estimate_ml_field_goal_volume(
        0.9, predicted_attempts=2.0, kicker_make_rate=0.85
    )
    assert attempts == 2.0
    assert 1.0 < made < 2.0


def test_blend_uses_distance_mixture_volume(monkeypatch):
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
                {"name": "Kicker", "career_fg_percentage": 88},
                {"team_red_zone_efficiency": 55},
                game_context={"predicted_attempts": 2.0},
            )

    assert meta["volume_model"] == "attempts_x_distance_mixture"
    assert meta["ml_projected_attempts"] == 2.0
    # Not the legacy 1.2 + 0.9*2.3 = 3.27
    assert blended < 2.5
    assert blended == meta["ml_projected_fgs"]
