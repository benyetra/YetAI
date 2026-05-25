"""Tests for NHL goalie saves ML shadow path (NHL-3.3)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from app.services.etl.nhl import goalie_saves_ml as gsm
from app.services.etl.nhl.backtest.runner import score_synthetic_rows
from app.services.etl.nhl.backtest.scorer import NHLBacktestScorer
from app.services.etl.nhl.goalie_saves_ml import (
    build_features_from_prediction,
    enrich_goalie_prediction_for_write,
    predict_saves_heuristic,
    predict_saves_ml,
    train_goalie_model,
)


def _sample_prediction(
    *,
    saves: float = 28.5,
    shots: float = 31.0,
    sv_pct: float = 0.918,
) -> dict:
    return {
        "predicted_saves": saves,
        "predicted_shots_against": shots,
        "predicted_save_pct": sv_pct,
        "goalie_recent_sv_pct": sv_pct,
        "goalie_season_sv_pct": 0.910,
        "opponent_shots_avg": shots,
        "is_home": True,
        "days_rest": 2,
        "rest_category": "normal",
        "confidence": 75,
    }


def test_build_features_pure_no_db():
    feats = build_features_from_prediction(_sample_prediction(saves=27.0, shots=30.0))
    assert feats["predicted_shots_against"] == 30.0
    assert feats["recent_sv_pct"] == 0.918
    assert feats["is_home"] == 1.0


def test_predict_saves_heuristic_matches_core_formula():
    feats = build_features_from_prediction(_sample_prediction(shots=32.0, sv_pct=0.900))
    assert predict_saves_heuristic(feats) == round(32.0 * 0.900, 1)


def test_enrich_shadow_without_model():
    pred = _sample_prediction()
    with patch.object(gsm, "predict_saves_ml_loaded", return_value=None):
        out = enrich_goalie_prediction_for_write(pred, {"starter_confirmation": {}})
    assert out["model_version"] == "heuristic-v1"
    assert out["predicted_saves"] == predict_saves_heuristic(
        build_features_from_prediction(pred)
    )
    assert "ml_shadow_saves" not in (out["features_used"] or {})


def test_enrich_shadow_stores_ml_when_disabled(monkeypatch):
    monkeypatch.delenv("NHL_GOALIE_ML_ENABLED", raising=False)
    pred = _sample_prediction()
    with patch.object(gsm, "predict_saves_ml_loaded", return_value=30.2):
        out = enrich_goalie_prediction_for_write(pred, {})
    assert out["model_version"] == "heuristic-v1"
    assert out["features_used"]["ml_shadow_saves"] == 30.2
    assert out["predicted_saves"] != 30.2


def test_enrich_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("NHL_GOALIE_ML_ENABLED", "1")
    pred = _sample_prediction()
    with patch.object(gsm, "predict_saves_ml_loaded", return_value=29.0):
        with patch.object(gsm, "_METADATA", {"model_version": "xgb-goalie-20260525"}):
            with patch.object(gsm, "_MODEL", object()):
                out = enrich_goalie_prediction_for_write(pred, {})
    assert out["predicted_saves"] == 29.0
    assert out["model_version"] == "xgb-goalie-20260525"


def test_ml_beats_heuristic_on_synthetic_fixture():
    """Train on data where saves correlate with pace/rest features."""
    rng = np.random.default_rng(7)
    n = 220
    rows = []
    actuals = []
    for _ in range(n):
        shots = rng.uniform(26.0, 36.0)
        sv = rng.uniform(0.88, 0.94)
        rest = rng.choice([0.0, 1.0])
        noise = rng.normal(0, 0.8)
        true_saves = shots * sv + 2.5 * rest + noise
        heuristic = round(shots * sv, 1)
        rows.append(
            {
                "recent_sv_pct": sv,
                "season_sv_pct": sv - 0.01,
                "home_away_sv_pct": sv,
                "opponent_shots_avg": shots,
                "predicted_shots_against": shots,
                "weighted_sv_pct": sv,
                "is_home": float(rng.choice([0.0, 1.0])),
                "days_rest": float(rng.integers(0, 4)),
                "rest_back_to_back": rest,
                "team_defense_shots": shots,
                "saves_line": 28.5,
                "heuristic_saves": heuristic,
            }
        )
        actuals.append(true_saves)

    X = pd.DataFrame(rows)
    y = pd.Series(actuals, name="actual_saves")
    model, metadata = train_goalie_model(
        (X, y),
        hyperparams={"n_estimators": 100, "max_depth": 3, "learning_rate": 0.1},
    )
    assert metadata["test_mae"] < 1.5

    holdout = X.iloc[-50:]
    h_heuristic = holdout["heuristic_saves"].to_numpy()
    actual_hold = y.iloc[-50:].to_numpy()
    ml_pred = np.array(
        [
            predict_saves_ml(model, holdout.iloc[i].to_dict())
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
                "market": "goalie",
                "predicted": 28.0,
                "actual": 30,
                "line": 27.5,
                "ml_predicted": 29.5,
            },
            {
                "market": "goalie",
                "predicted": 26.0,
                "actual": 25,
                "line": 26.5,
                "features_used": {"ml_shadow_saves": 25.5},
            },
        ]
    )
    metrics = scorer.compute_goalie_metrics()
    assert metrics["n_goalie"] == 2
    assert metrics["goalie_ml_n"] == 2
    assert "methods" in metrics
    assert metrics["methods"]["heuristic"]["n"] == 2
    assert metrics["methods"]["ml"]["n"] == 2


def test_backtest_scorer_ml_ou_grading():
    scorer = NHLBacktestScorer()
    scorer.add_goalie_result(28.0, 30, saves_line=27.5, ml_predicted_saves=29.0)
    metrics = scorer.compute_goalie_metrics()
    assert metrics["goalie_ml_mae"] == 1.0
    assert metrics["methods"]["ml"]["ou_hit_rate"] == 1.0
