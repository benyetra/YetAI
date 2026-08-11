"""Tests for kicker attempts regressor + volume resolve path."""

from __future__ import annotations

from unittest.mock import patch

from app.services.etl.nfl.kicker_attempts import (
    FEATURE_NAMES,
    build_attempt_features,
    build_attempts_dataset_from_fg_csv,
    train_attempts_model,
)
from app.services.etl.nfl.kicker_volume import expected_fg_made, resolve_attempts


def test_build_attempt_features_defaults():
    feats = build_attempt_features({"implied_team_total": 24.0, "spread": -3.5})
    assert feats["implied_team_total"] == 24.0
    assert feats["spread"] == -3.5
    assert set(FEATURE_NAMES) == set(feats.keys())


def test_resolve_attempts_prefers_explicit():
    att, src = resolve_attempts(attempts=2.2)
    assert att == 2.2
    assert src == "explicit"


def test_resolve_attempts_falls_back_heuristic():
    with patch(
        "app.services.etl.nfl.kicker_attempts.predict_attempts_ml", return_value=None
    ):
        att, src = resolve_attempts({"implied_team_total": 23.0})
    assert 1.1 <= att <= 2.8
    assert src == "heuristic"


def test_expected_fg_made_includes_attempts_source():
    with patch(
        "app.services.etl.nfl.kicker_attempts.predict_attempts_ml", return_value=2.1
    ):
        projected, meta = expected_fg_made(
            team_data={"implied_team_total": 22.0},
            classifier_make_prob=0.8,
        )
    assert projected > 0
    assert meta["attempts_source"] == "gbm_attempts"
    assert meta["projected_attempts"] == 2.1


def test_train_attempts_model_from_csv_smoke():
    features, target = build_attempts_dataset_from_fg_csv()
    assert len(features) >= 40
    assert len(target) == len(features)
    # Subsample for speed
    model, meta = train_attempts_model((features.iloc[:200], target.iloc[:200]))
    assert meta["holdout_mae"] >= 0
    assert "gbm-kicker-attempts" in meta["model_version"]
    _ = model
