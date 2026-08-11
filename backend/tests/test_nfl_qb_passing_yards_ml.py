"""Tests for NFL QB passing yards ML shadow path (NFL-4.3)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from app.services.etl.nfl import qb_passing_yards_ml as qbm
from app.services.etl.nfl.qb_features import FEATURE_NAMES
from app.services.etl.nfl.qb_passing_yards_ml import (
    build_features_from_tier_prediction,
    enrich_qb_prediction_for_write,
    predict_yards_ml,
    train_qb_yards_model,
)


def _tier_pred(*, yards: float = 245.0) -> dict:
    return {
        "predicted_passing_yards": yards,
        "confidence": 0.72,
        "prediction_method": "dynamic_starter",
    }


def test_build_features_from_tier():
    feats = build_features_from_tier_prediction(
        _tier_pred(yards=250.0), season=2024, week=5, is_backup=True
    )
    assert feats["tier_yards"] == 250.0
    assert feats["is_backup"] == 1.0
    assert feats["week"] == 5.0
    assert feats["rolling_yards_l3"] == 250.0
    assert "opp_pass_yds_allowed" in feats


def test_build_features_with_context():
    feats = build_features_from_tier_prediction(
        _tier_pred(yards=250.0),
        season=2024,
        week=5,
        context={"rolling_yards_l3": 270.0, "is_home": 1.0},
    )
    assert feats["rolling_yards_l3"] == 270.0
    assert feats["is_home"] == 1.0


def test_enrich_shadow_without_model():
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=None):
        out = enrich_qb_prediction_for_write(
            _tier_pred(), season=2024, week=3, is_backup=False
        )
    assert out["model_version"] == "tier-v2"
    assert out["predicted_passing_yards"] == 245.0
    assert "ml_shadow_yards" not in (out["feature_importance"] or {})


def test_enrich_shadow_stores_ml_when_disabled(monkeypatch):
    monkeypatch.delenv("NFL_QB_ML_ENABLED", raising=False)
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=252.0):
        out = enrich_qb_prediction_for_write(_tier_pred(), season=2024, week=3)
    assert out["model_version"] == "tier-v2"
    assert out["feature_importance"]["ml_shadow_yards"] == 252.0
    assert out["predicted_passing_yards"] == 245.0
    assert "features" in out["feature_importance"]


def test_enrich_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("NFL_QB_ML_ENABLED", "1")
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=260.0):
        with patch.object(qbm, "_METADATA", {"model_version": "gbm-qb-yards-20260525"}):
            with patch.object(qbm, "_MODEL", object()):
                out = enrich_qb_prediction_for_write(_tier_pred(), season=2024, week=3)
    assert out["predicted_passing_yards"] == 260.0
    assert out["prediction_method"] == "gbm_qb_yards"


def test_train_qb_yards_model_smoke():
    n = 50
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "tier_yards": np.linspace(200, 280, n),
            "is_backup": np.zeros(n),
            "week": np.ones(n),
            "confidence": np.full(n, 0.7),
            "season": np.full(n, 2024),
            "rolling_yards_l3": np.linspace(195, 275, n),
            "rolling_yards_l5": np.linspace(198, 278, n),
            "season_avg_yards": np.linspace(200, 270, n),
            "opp_pass_yds_allowed": np.full(n, 220.0),
            "is_home": rng.integers(0, 2, n).astype(float),
            "rest_days": np.full(n, 7.0),
            "implied_team_total": np.full(n, 23.0),
            "wind_speed": np.full(n, 8.0),
            "temperature": np.full(n, 60.0),
            "dome": np.zeros(n),
        }
    )
    assert list(df.columns) == list(FEATURE_NAMES) or set(FEATURE_NAMES).issubset(
        set(df.columns)
    )
    y = (
        0.55 * df["tier_yards"]
        + 0.25 * df["rolling_yards_l3"]
        + 0.1 * df["opp_pass_yds_allowed"]
        + rng.normal(0, 12, n)
    )
    model, meta = train_qb_yards_model((df, y))
    pred = predict_yards_ml(model, df.iloc[0].to_dict())
    assert 150 <= pred <= 400
    assert meta["holdout_mae"] >= 0
    assert set(FEATURE_NAMES).issubset(set(meta["features"]))
