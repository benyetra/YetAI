"""Tests for WNBA totals residual ML."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
from app.services.etl.wnba import totals_ml as tml
from app.services.etl.wnba.ml_training.train_totals_model import train_residual_model
from app.services.etl.wnba.totals_ml import enrich_projection, features_from_projection


def _sample_projection(heuristic: float = 164.0, market: float | None = 162.5) -> dict:
    return {
        "game_date": date(2026, 6, 1),
        "home_team": "Indiana Fever",
        "away_team": "Connecticut Sun",
        "projected_total": heuristic,
        "base_projection": 163.0,
        "expected_pace": 80.0,
        "home_offensive_rating": 102.0,
        "away_offensive_rating": 101.0,
        "home_defensive_rating": 100.0,
        "away_defensive_rating": 101.0,
        "injury_adjustment": -1.0,
        "rest_adjustment": 0.0,
        "venue_adjustment": 0.0,
        "form_adjustment": 0.5,
        "total_adjustment": -0.5,
        "market_total": market,
        "edge": 1.5,
        "recommendation": "NO_PLAY",
        "confidence_score": 0.5,
        "factors": {},
    }


def test_features_from_projection_includes_heuristic_and_market():
    feats = features_from_projection(_sample_projection(heuristic=165.5, market=163.0))
    assert feats["heuristic_total"] == 165.5
    assert feats["market_total"] == 163.0
    assert feats["market_minus_heuristic"] == -2.5
    assert feats["expected_pace"] == 80.0


def test_enrich_projection_shadow_without_model():
    proj = _sample_projection()
    with patch.object(tml, "predict_residual", return_value=None):
        out = enrich_projection(proj)
    assert out["heuristic_total"] == 164.0
    assert out["projected_total"] == 164.0
    assert out["factors"]["ml_shadow"]["ml_total"] is None


def test_enrich_projection_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("WNBA_TOTALS_ML_ENABLED", "1")
    proj = _sample_projection(heuristic=164.0, market=162.0)
    with patch.object(tml, "predict_residual", return_value=3.0):
        out = enrich_projection(proj)
    assert out["heuristic_total"] == 164.0
    assert out["ml_total"] == 167.0
    assert out["projected_total"] == 167.0
    assert out["edge"] == 5.0
    assert out["recommendation"] == "OVER"


def test_residual_model_reduces_mae_on_synthetic_fixture():
    rng = np.random.default_rng(42)
    n = 200
    heuristic = rng.uniform(155.0, 175.0, size=n)
    pace = rng.uniform(78.0, 82.0, size=n)
    injury = rng.uniform(-4.0, 0.0, size=n)
    true_residual = 0.35 * (pace - 80.0) + 0.5 * injury + rng.normal(0, 0.3, size=n)

    rows = []
    for i in range(n):
        rows.append(
            features_from_projection(
                {
                    "projected_total": heuristic[i],
                    "base_projection": heuristic[i] - 2.0,
                    "expected_pace": pace[i],
                    "home_offensive_rating": 102.0,
                    "away_offensive_rating": 101.0,
                    "home_defensive_rating": 100.0,
                    "away_defensive_rating": 101.0,
                    "injury_adjustment": injury[i],
                    "rest_adjustment": 0.0,
                    "venue_adjustment": 0.0,
                    "form_adjustment": 0.0,
                    "total_adjustment": injury[i],
                    "market_total": heuristic[i] - 1.0,
                }
            )
        )

    X = pd.DataFrame(rows)
    y = pd.Series(true_residual, name="residual")
    game_dates = pd.Series(
        [date(2024, 5, 1) + timedelta(days=i) for i in range(n)], name="game_date"
    )
    model, metadata = train_residual_model(
        X,
        y,
        game_dates,
        hyperparams={"n_estimators": 80, "max_depth": 3, "learning_rate": 0.1},
    )
    assert metadata["holdout"]["residual_mae"] < 1.0

    holdout = X.iloc[-40:]
    h_hold = heuristic[-40:]
    actual_hold = heuristic[-40:] + true_residual[-40:]
    pred_residual = model.predict(holdout)
    ml_pred = h_hold + pred_residual

    heuristic_mae = float(np.mean(np.abs(actual_hold - h_hold)))
    ml_mae = float(np.mean(np.abs(actual_hold - ml_pred)))
    assert ml_mae < heuristic_mae


def test_shadow_from_factors_roundtrip():
    factors = {"ml_shadow": {"heuristic_total": 163.0, "ml_total": 166.0}}
    shadow = tml.shadow_from_factors(factors)
    assert shadow["heuristic_total"] == 163.0
    assert shadow["ml_total"] == 166.0
