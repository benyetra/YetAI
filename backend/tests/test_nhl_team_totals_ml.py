"""Tests for NHL team totals ML shadow path (NHL-3.4)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from app.services.etl.nhl import team_totals_ml as ttm
from app.services.etl.nhl.backtest.runner import score_synthetic_rows
from app.services.etl.nhl.backtest.scorer import NHLBacktestScorer
from app.services.etl.nhl.team_totals_ml import (
    build_features_from_prediction,
    enrich_team_totals_prediction_for_write,
    predict_total_heuristic,
    predict_total_ml,
    train_team_totals_model,
)


def _sample_prediction(*, total: float = 6.2) -> dict:
    return {
        "predicted_total_goals": total,
        "predicted_home_goals": 3.3,
        "predicted_away_goals": 2.9,
        "home_offense_rating": 3.1,
        "away_offense_rating": 2.8,
        "home_defense_rating": 2.9,
        "away_defense_rating": 3.0,
        "combined_pace": 62.0,
        "home_pp_pct": 22.0,
        "away_pp_pct": 21.0,
        "home_pk_pct": 81.0,
        "away_pk_pct": 79.0,
        "suggested_ou_line": 6.0,
        "confidence": 80,
    }


def test_build_features_from_prediction():
    feats = build_features_from_prediction(_sample_prediction(total=6.5))
    assert feats["heuristic_total"] == 6.5
    assert feats["combined_pace"] == 62.0


def test_predict_total_heuristic():
    feats = build_features_from_prediction(_sample_prediction())
    assert predict_total_heuristic(feats) == 6.2


def test_enrich_shadow_without_model():
    pred = _sample_prediction()
    with patch.object(ttm, "predict_total_ml_loaded", return_value=None):
        out = enrich_team_totals_prediction_for_write(pred)
    assert out["model_version"] == "heuristic-v1"
    assert "ml_shadow_total" not in (out.get("features_used") or {})


def test_enrich_shadow_stores_ml_when_disabled(monkeypatch):
    monkeypatch.delenv("NHL_TOTALS_ML_ENABLED", raising=False)
    pred = _sample_prediction()
    with patch.object(ttm, "predict_total_ml_loaded", return_value=6.8):
        out = enrich_team_totals_prediction_for_write(pred)
    assert out["features_used"]["ml_shadow_total"] == 6.8
    assert out["predicted_total_goals"] == 6.2


def test_enrich_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("NHL_TOTALS_ML_ENABLED", "1")
    pred = _sample_prediction()
    with patch.object(ttm, "predict_total_ml_loaded", return_value=6.6):
        with patch.object(ttm, "_METADATA", {"model_version": "gbm-totals-20260525"}):
            with patch.object(ttm, "_MODEL", object()):
                out = enrich_team_totals_prediction_for_write(pred)
    assert out["predicted_total_goals"] == 6.6
    assert out["model_version"] == "gbm-totals-20260525"


def test_residual_model_beats_heuristic_on_synthetic_fixture():
    rng = np.random.default_rng(13)
    n = 120
    rows = []
    residuals = []
    for _ in range(n):
        heuristic = rng.uniform(5.0, 7.5)
        pace = rng.uniform(55.0, 68.0)
        home_off = rng.uniform(2.5, 3.8)
        residual = 0.04 * (pace - 60.0) + 0.08 * (home_off - 3.0) + rng.normal(0, 0.15)
        rows.append(
            {
                "heuristic_total": heuristic,
                "predicted_home_goals": home_off,
                "predicted_away_goals": heuristic - home_off,
                "home_offense_rating": home_off,
                "away_offense_rating": 3.0,
                "home_defense_rating": 3.0,
                "away_defense_rating": 3.0,
                "combined_pace": pace,
                "home_pp_pct": 20.0,
                "away_pp_pct": 20.0,
                "home_pk_pct": 80.0,
                "away_pk_pct": 80.0,
                "suggested_ou_line": round(heuristic * 2) / 2,
                "market_ou_line": 6.0,
            }
        )
        residuals.append(residual)

    X = pd.DataFrame(rows)
    y = pd.Series(residuals, name="residual")
    model, metadata = train_team_totals_model((X, y))
    assert metadata["test_mae"] < 0.35

    holdout = X.iloc[-30:]
    res_hold = y.iloc[-30:].to_numpy()
    heuristic_hold = holdout["heuristic_total"].to_numpy()
    actual_hold = heuristic_hold + res_hold
    ml_pred = np.array(
        [
            predict_total_ml(model, holdout.iloc[i].to_dict())
            for i in range(len(holdout))
        ]
    )
    heuristic_mae = float(np.mean(np.abs(actual_hold - heuristic_hold)))
    ml_mae = float(np.mean(np.abs(actual_hold - ml_pred)))
    assert ml_mae < heuristic_mae


def test_backtest_scores_heuristic_and_ml_totals():
    scorer = score_synthetic_rows(
        [
            {
                "market": "totals",
                "predicted": 6.0,
                "actual": 7,
                "line": 6.5,
                "ml_predicted": 6.8,
            },
            {
                "market": "totals",
                "predicted": 5.5,
                "actual": 5,
                "line": 5.5,
                "features_used": {"ml_shadow_total": 5.2},
            },
        ]
    )
    metrics = scorer.compute_totals_metrics()
    assert metrics["n_totals"] == 2
    assert metrics["totals_ml_n"] == 2
    assert metrics["methods"]["ml"]["n"] == 2


def test_backtest_scorer_totals_ml_ou():
    scorer = NHLBacktestScorer()
    scorer.add_totals_result(6.0, 7, ou_line=6.5, ml_predicted_total=6.7)
    metrics = scorer.compute_totals_metrics()
    assert metrics["totals_ml_mae"] == 0.3
    assert metrics["methods"]["ml"]["ou_hit_rate"] == 1.0
