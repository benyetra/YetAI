"""Tests for NHL player SOG ML shadow path (NHL-3.4)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from app.services.etl.nhl import player_shots_ml as psm
from app.services.etl.nhl.backtest.runner import score_synthetic_rows
from app.services.etl.nhl.backtest.scorer import NHLBacktestScorer
from app.services.etl.nhl.player_shots_ml import (
    build_features_from_prediction,
    enrich_player_shots_prediction_for_write,
    predict_shots_heuristic,
    predict_shots_ml,
    train_player_shots_model,
)


def _sample_prediction(*, shots: float = 3.2) -> dict:
    return {
        "predicted_shots": shots,
        "baseline_shots": 3.0,
        "ice_time_adjustment": 1.08,
        "opponent_shots_adjustment": 1.05,
        "blocks_adjustment": 1.0,
        "position_adjustment": 1.0,
        "home_ice_adjustment": 1.05,
        "player_toi_per_game": 1100.0,
        "opponent_shots_against_pg": 31.0,
        "opponent_blocks_pg": 15.0,
        "player_position": "C",
        "is_home": True,
        "confidence": 75,
    }


def test_build_features_pure_no_db():
    feats = build_features_from_prediction(_sample_prediction(shots=3.5))
    assert feats["baseline_shots"] == 3.0
    assert feats["is_home"] == 1.0
    assert feats["is_defenseman"] == 0.0


def test_predict_shots_heuristic_matches_multipliers():
    feats = build_features_from_prediction(_sample_prediction())
    expected = round(3.0 * 1.08 * 1.05 * 1.0 * 1.0 * 1.05, 2)
    assert predict_shots_heuristic(feats) == expected


def test_enrich_shadow_without_model():
    pred = _sample_prediction()
    with patch.object(psm, "predict_shots_ml_loaded", return_value=None):
        out = enrich_player_shots_prediction_for_write(pred, extra_features={"k": 1})
    assert out["model_version"] == "heuristic-v1"
    assert "ml_shadow_sog" not in (out["features_used"] or {})


def test_enrich_shadow_stores_ml_when_disabled(monkeypatch):
    monkeypatch.delenv("NHL_PLAYER_SOG_ML_ENABLED", raising=False)
    pred = _sample_prediction()
    with patch.object(psm, "predict_shots_ml_loaded", return_value=4.1):
        out = enrich_player_shots_prediction_for_write(pred)
    assert out["model_version"] == "heuristic-v1"
    assert out["features_used"]["ml_shadow_sog"] == 4.1
    assert out["predicted_shots"] != 4.1


def test_enrich_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("NHL_PLAYER_SOG_ML_ENABLED", "1")
    pred = _sample_prediction()
    with patch.object(psm, "predict_shots_ml_loaded", return_value=3.9):
        with patch.object(psm, "_METADATA", {"model_version": "xgb-sog-20260525"}):
            with patch.object(psm, "_MODEL", object()):
                out = enrich_player_shots_prediction_for_write(pred)
    assert out["predicted_shots"] == 3.9
    assert out["model_version"] == "xgb-sog-20260525"


def test_ml_beats_heuristic_on_synthetic_fixture():
    rng = np.random.default_rng(11)
    n = 200
    rows = []
    actuals = []
    for _ in range(n):
        baseline = rng.uniform(1.5, 5.0)
        ice = rng.uniform(0.85, 1.15)
        opp = rng.uniform(0.9, 1.1)
        home = rng.choice([0.0, 1.0])
        rest = rng.normal(0, 0.3)
        true_shots = baseline * ice * opp * (1.05 if home else 1.0) + rest
        heuristic = round(baseline * ice * opp * (1.05 if home else 1.0), 2)
        rows.append(
            {
                "baseline_shots": baseline,
                "ice_time_adjustment": ice,
                "opponent_shots_adjustment": opp,
                "blocks_adjustment": 1.0,
                "position_adjustment": 1.0,
                "home_ice_adjustment": 1.05 if home else 1.0,
                "player_toi_per_game": 1000.0,
                "opponent_shots_against_pg": 30.0,
                "opponent_blocks_pg": 15.0,
                "is_home": home,
                "is_defenseman": 0.0,
                "shots_line": 3.5,
                "heuristic_shots": heuristic,
            }
        )
        actuals.append(true_shots)

    X = pd.DataFrame(rows)
    y = pd.Series(actuals, name="actual_shots")
    model, metadata = train_player_shots_model(
        (X, y),
        hyperparams={"n_estimators": 80, "max_depth": 3, "learning_rate": 0.1},
    )
    assert metadata["test_mae"] < 0.6

    holdout = X.iloc[-40:]
    h_heuristic = holdout["heuristic_shots"].to_numpy()
    actual_hold = y.iloc[-40:].to_numpy()
    ml_pred = np.array(
        [
            predict_shots_ml(model, holdout.iloc[i].to_dict())
            for i in range(len(holdout))
        ]
    )
    heuristic_mae = float(np.mean(np.abs(actual_hold - h_heuristic)))
    ml_mae = float(np.mean(np.abs(actual_hold - ml_pred)))
    assert ml_mae < heuristic_mae


def test_backtest_scores_heuristic_and_ml_paths():
    scorer = score_synthetic_rows(
        [
            {
                "market": "sog",
                "predicted": 3.0,
                "actual": 4,
                "line": 3.5,
                "ml_predicted": 3.8,
            },
            {
                "market": "sog",
                "predicted": 2.5,
                "actual": 2,
                "line": 2.5,
                "features_used": {"ml_shadow_sog": 2.2},
            },
        ]
    )
    metrics = scorer.compute_sog_metrics()
    assert metrics["n_sog"] == 2
    assert metrics["sog_ml_n"] == 2
    assert metrics["methods"]["ml"]["n"] == 2


def test_backtest_scorer_ml_ou_grading():
    scorer = NHLBacktestScorer()
    scorer.add_sog_result(3.0, 4, shots_line=3.5, ml_predicted_shots=3.8)
    metrics = scorer.compute_sog_metrics()
    assert metrics["sog_ml_mae"] == 0.2
    assert metrics["methods"]["ml"]["ou_hit_rate"] == 1.0
