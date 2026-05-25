"""Tests for NBA totals residual ML (BKB-2.5)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
from app.services.etl.nba import totals_ml as tml
from app.services.etl.nba.ml_training.train_totals_model import train_residual_model
from app.services.etl.nba.totals_ml import enrich_projection, features_from_projection


def _sample_projection(heuristic: float = 220.0, market: float | None = 218.5) -> dict:
    return {
        "game_date": date(2026, 5, 19),
        "home_team": "Boston Celtics",
        "away_team": "New York Knicks",
        "projected_total": heuristic,
        "base_projection": 218.0,
        "expected_pace": 99.0,
        "home_offensive_rating": 115.0,
        "away_offensive_rating": 114.0,
        "home_defensive_rating": 112.0,
        "away_defensive_rating": 113.0,
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
    feats = features_from_projection(_sample_projection(heuristic=221.5, market=219.0))
    assert feats["heuristic_total"] == 221.5
    assert feats["market_total"] == 219.0
    assert feats["expected_pace"] == 99.0


def test_enrich_projection_shadow_without_model():
    proj = _sample_projection()
    with patch.object(tml, "predict_residual", return_value=None):
        out = enrich_projection(proj)
    assert out["heuristic_total"] == 220.0
    assert out["projected_total"] == 220.0
    assert out["factors"]["ml_shadow"]["ml_total"] is None


def test_enrich_projection_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("NBA_TOTALS_ML_ENABLED", "1")
    proj = _sample_projection(heuristic=220.0, market=218.0)
    with patch.object(tml, "predict_residual", return_value=3.0):
        out = enrich_projection(proj)
    assert out["heuristic_total"] == 220.0
    assert out["ml_total"] == 223.0
    assert out["projected_total"] == 223.0
    assert out["edge"] == 5.0
    assert out["recommendation"] == "OVER"


def test_residual_model_reduces_mae_on_synthetic_fixture():
    """Train on synthetic data where residual is predictable from features."""
    rng = np.random.default_rng(42)
    n = 200
    heuristic = rng.uniform(210.0, 235.0, size=n)
    pace = rng.uniform(96.0, 102.0, size=n)
    injury = rng.uniform(-4.0, 0.0, size=n)
    true_residual = 0.35 * (pace - 99.0) + 0.5 * injury + rng.normal(0, 0.3, size=n)
    actual = heuristic + true_residual

    rows = []
    for i in range(n):
        rows.append(
            features_from_projection(
                {
                    "projected_total": heuristic[i],
                    "base_projection": heuristic[i] - 2.0,
                    "expected_pace": pace[i],
                    "home_offensive_rating": 114.0,
                    "away_offensive_rating": 113.0,
                    "home_defensive_rating": 112.0,
                    "away_defensive_rating": 113.0,
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
    model, metadata = train_residual_model(
        X, y, hyperparams={"n_estimators": 80, "max_depth": 3, "learning_rate": 0.1}
    )
    assert metadata["test_mae"] < 1.0

    holdout = X.iloc[-40:]
    h_hold = heuristic[-40:]
    actual_hold = actual[-40:]
    pred_residual = model.predict(holdout)
    ml_pred = h_hold + pred_residual

    heuristic_mae = float(np.mean(np.abs(actual_hold - h_hold)))
    ml_mae = float(np.mean(np.abs(actual_hold - ml_pred)))
    assert ml_mae < heuristic_mae


def test_shadow_from_factors_roundtrip():
    factors = {"ml_shadow": {"heuristic_total": 219.0, "ml_total": 222.0}}
    shadow = tml.shadow_from_factors(factors)
    assert shadow["heuristic_total"] == 219.0
    assert shadow["ml_total"] == 222.0
