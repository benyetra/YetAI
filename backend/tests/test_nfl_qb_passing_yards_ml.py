"""Tests for NFL QB passing yards ML shadow path (NFL-4.3+)."""

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
        "prediction_interval_lower": yards - 32,
        "prediction_interval_upper": yards + 32,
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
    assert "opp_def_epa" in feats
    assert "injury_risk" in feats


def test_build_features_with_context():
    feats = build_features_from_tier_prediction(
        _tier_pred(yards=250.0),
        season=2024,
        week=5,
        context={
            "rolling_yards_l3": 270.0,
            "is_home": 1.0,
            "opp_def_epa": 0.12,
            "injury_status": "Questionable",
        },
    )
    assert feats["rolling_yards_l3"] == 270.0
    assert feats["is_home"] == 1.0
    assert feats["opp_def_epa"] == 0.12
    assert feats["injury_risk"] == 0.55


def test_enrich_shadow_without_model():
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=None):
        out = enrich_qb_prediction_for_write(
            _tier_pred(), season=2024, week=3, is_backup=False
        )
    assert out["model_version"] == "tier-v3"
    assert out["predicted_passing_yards"] == 245.0
    assert out["prediction_interval_lower"] == 213.0
    assert "ml_shadow_yards" not in (out["feature_importance"] or {})


def test_enrich_shadow_stores_ml_when_disabled(monkeypatch):
    monkeypatch.delenv("NFL_QB_ML_ENABLED", raising=False)
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=252.0):
        out = enrich_qb_prediction_for_write(_tier_pred(), season=2024, week=3)
    assert out["model_version"] == "tier-v3"
    assert out["feature_importance"]["ml_shadow_yards"] == 252.0
    assert out["predicted_passing_yards"] == 245.0
    assert "features" in out["feature_importance"]


def test_enrich_promotes_ml_when_enabled(monkeypatch):
    monkeypatch.setenv("NFL_QB_ML_ENABLED", "1")
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=260.0):
        with patch.object(
            qbm,
            "_METADATA",
            {
                "model_version": "gbm-qb-yards-20260525",
                "target": "actual_passing_yards",
            },
        ):
            with patch.object(qbm, "_MODEL", object()):
                out = enrich_qb_prediction_for_write(_tier_pred(), season=2024, week=3)
    assert out["predicted_passing_yards"] == 260.0
    assert out["prediction_method"] == "gbm_qb_yards"
    assert out["prediction_interval_lower"] < 260.0


def test_train_qb_yards_model_smoke():
    n = 50
    rng = np.random.default_rng(42)
    base = {
        "tier_yards": np.linspace(200, 280, n),
        "is_backup": np.zeros(n),
        "week": np.arange(1, n + 1) % 18 + 1,
        "confidence": np.full(n, 0.7),
        "season": np.concatenate([np.full(25, 2024), np.full(25, 2025)]),
        "rolling_yards_l3": np.linspace(195, 275, n),
        "rolling_yards_l5": np.linspace(198, 278, n),
        "season_avg_yards": np.linspace(200, 270, n),
        "rolling_attempts_l3": np.full(n, 34.0),
        "rolling_ypa_l3": np.full(n, 7.0),
        "rolling_comp_pct_l3": np.full(n, 0.65),
        "opp_pass_yds_allowed": np.full(n, 220.0),
        "opp_def_epa": rng.normal(0, 0.1, n),
        "opp_pressure_rate": np.full(n, 0.25),
        "injury_risk": np.zeros(n),
        "is_home": rng.integers(0, 2, n).astype(float),
        "rest_days": np.full(n, 7.0),
        "implied_team_total": np.full(n, 23.0),
        "wind_speed": np.full(n, 8.0),
        "temperature": np.full(n, 60.0),
        "dome": np.zeros(n),
        "total_line": np.full(n, 46.0),
        "spread_line": np.zeros(n),
        "pass_yds_line": np.linspace(200, 280, n),
        "line_minus_tier": np.zeros(n),
        "opp_cover_base": np.full(n, 3.0),
        "opp_man_zone": np.zeros(n),
        "opp_scheme_pressure": np.full(n, 0.5),
    }
    df = pd.DataFrame(base)
    assert set(FEATURE_NAMES).issubset(set(df.columns))
    y = (
        0.55 * df["tier_yards"]
        + 0.25 * df["rolling_yards_l3"]
        + 0.1 * df["opp_pass_yds_allowed"]
        + rng.normal(0, 12, n)
    )
    model, meta = train_qb_yards_model((df, y), residual_target=True)
    pred = predict_yards_ml(model, df.iloc[0].to_dict(), residual_target=True)
    assert 150 <= pred <= 400
    assert meta["holdout_mae"] >= 0
    assert meta["residual_target"] is True
    assert "residual" in meta["target"]
    assert meta["cv_split"] == "time_ordered_last_20pct"
    assert meta["baseline"] == "market_aware_tier_line_blend"
    assert set(FEATURE_NAMES).issubset(set(meta["features"]))


def test_predict_yards_ml_uses_market_baseline():
    class _Stub:
        def predict(self, X):  # noqa: N803
            return np.array([5.0])

    feats = {
        "tier_yards": 250.0,
        "pass_yds_line": 270.0,
        "line_minus_tier": 20.0,
    }
    # baseline = 260; + residual 5 → 265
    assert predict_yards_ml(_Stub(), feats, residual_target=True) == 265.0


def test_reinject_pass_yds_line():
    from app.services.etl.nfl.qb_passing_yards_ml import reinject_pass_yds_line

    out = reinject_pass_yds_line(
        {"tier_yards": 250.0, "pass_yds_line": 250.0, "line_minus_tier": 0.0},
        ou_line=275.5,
    )
    assert out["pass_yds_line"] == 275.5
    assert out["line_minus_tier"] == 25.5


def test_enrich_promotes_residual_method(monkeypatch):
    monkeypatch.setenv("NFL_QB_ML_ENABLED", "1")
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=260.0):
        with patch.object(
            qbm,
            "_METADATA",
            {
                "model_version": "gbm-qb-residual-20260811",
                "target": "residual_actual_minus_tier",
            },
        ):
            with patch.object(qbm, "_MODEL", object()):
                out = enrich_qb_prediction_for_write(_tier_pred(), season=2024, week=3)
    assert out["predicted_passing_yards"] == 260.0
    assert out["prediction_method"] == "gbm_qb_residual"
