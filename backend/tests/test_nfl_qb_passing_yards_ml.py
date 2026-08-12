"""Tests for NFL QB passing yards ML shadow path (NFL-4.3+)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from app.services.etl.nfl import qb_passing_yards_ml as qbm
from app.services.etl.nfl.qb_features import FEATURE_NAMES
from app.services.etl.nfl.qb_passing_yards_ml import (
    PROMOTE_BASELINE_MODE,
    PROMOTE_FEATURE_NAMES,
    build_features_from_tier_prediction,
    enrich_qb_prediction_for_write,
    predict_yards_ml,
    train_promote_qb_yards_model,
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
                out = enrich_qb_prediction_for_write(
                    _tier_pred(),
                    season=2024,
                    week=3,
                    context={
                        "pass_yds_line": 255.0,
                        "line_is_real": True,
                        "dynamic_tier_yards": 245.0,
                    },
                )
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
        "rolling_air_yards_l3": np.full(n, 7.5),
        "rolling_dropbacks_l3": np.full(n, 36.0),
        "rolling_sack_rate_l3": np.full(n, 0.07),
        "opp_pass_yds_allowed": np.full(n, 220.0),
        "opp_air_yards_allowed": np.full(n, 7.5),
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
        "line_is_real": np.ones(n),
        "market_residual_l3": np.zeros(n),
        "line_minus_rolling": np.zeros(n),
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
    assert meta["fit_full"] is False
    assert meta["baseline"] == "market_aware_tier_line_blend"
    assert set(FEATURE_NAMES).issubset(set(meta["features"]))
    assert meta["n_train"] < len(df)
    assert meta["cv_n_train"] == meta["n_train"]


def test_train_qb_yards_model_fit_full_uses_all_rows():
    n = 50
    rng = np.random.default_rng(7)
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
        "rolling_air_yards_l3": np.full(n, 7.5),
        "rolling_dropbacks_l3": np.full(n, 36.0),
        "rolling_sack_rate_l3": np.full(n, 0.07),
        "opp_pass_yds_allowed": np.full(n, 220.0),
        "opp_air_yards_allowed": np.full(n, 7.5),
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
        "line_is_real": np.ones(n),
        "market_residual_l3": np.zeros(n),
        "line_minus_rolling": np.zeros(n),
        "opp_cover_base": np.full(n, 3.0),
        "opp_man_zone": np.zeros(n),
        "opp_scheme_pressure": np.full(n, 0.5),
    }
    df = pd.DataFrame(base)
    y = 0.6 * df["tier_yards"] + 0.2 * df["rolling_yards_l3"] + rng.normal(0, 10, n)
    model, meta = train_qb_yards_model((df, y), residual_target=True, fit_full=True)
    assert meta["fit_full"] is True
    assert meta["n_train"] == n
    assert meta["cv_n_train"] < n
    assert meta["cv_split"] == "time_ordered_last_20pct_then_refit_full"
    pred = predict_yards_ml(model, df.iloc[0].to_dict(), residual_target=True)
    assert 150 <= pred <= 400


def test_train_qb_yards_model_tier_baseline_and_v5_features():
    from app.services.etl.nfl.qb_features import V5_FEATURE_NAMES

    n = 40
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            name: (
                np.linspace(200, 260, n)
                if name in ("tier_yards", "rolling_yards_l3", "pass_yds_line")
                else np.full(n, 1.0 if name == "line_is_real" else 0.0)
            )
            for name in FEATURE_NAMES
        }
    )
    df["season"] = np.concatenate([np.full(20, 2024), np.full(20, 2025)])
    df["week"] = np.arange(1, n + 1)
    y = df["tier_yards"] + rng.normal(0, 8, n)
    model, meta = train_qb_yards_model(
        (df, y),
        residual_target=True,
        fit_full=True,
        feature_order=list(V5_FEATURE_NAMES),
        baseline_mode="tier",
    )
    assert meta["baseline_mode"] == "tier"
    assert meta["n_train"] == n
    assert meta["features"] == list(V5_FEATURE_NAMES)
    pred = predict_yards_ml(
        model,
        df.iloc[0].to_dict(),
        feature_order=list(V5_FEATURE_NAMES),
        residual_target=True,
        baseline_mode="tier",
    )
    assert 150 <= pred <= 400


def test_train_promote_qb_yards_model_market_v6_fit_full():
    n = 50
    rng = np.random.default_rng(11)
    df = pd.DataFrame(
        {
            name: (
                np.linspace(200, 260, n)
                if name
                in (
                    "tier_yards",
                    "rolling_yards_l3",
                    "pass_yds_line",
                    "season_avg_yards",
                )
                else np.full(n, 1.0 if name == "line_is_real" else 0.0)
            )
            for name in FEATURE_NAMES
        }
    )
    df["season"] = np.concatenate([np.full(25, 2024), np.full(25, 2025)])
    df["week"] = np.arange(1, n + 1)
    y = df["tier_yards"] + 0.2 * df["rolling_yards_l3"] + rng.normal(0, 8, n)
    model, meta = train_promote_qb_yards_model((df, y), residual_target=True)
    assert meta["baseline_mode"] == PROMOTE_BASELINE_MODE == "market"
    assert meta["fit_full"] is True
    assert meta["n_train"] == n
    assert meta["features"] == list(PROMOTE_FEATURE_NAMES)
    assert "pass_yds_line" in meta["features"]
    assert meta.get("promote_path") == "market_residual_v6"
    assert meta.get("promote_hp_selected") in {"default", "shallow", "strong_reg"}
    assert isinstance(meta.get("promote_hp_sweep"), list)
    assert len(meta["promote_hp_sweep"]) >= 2
    pred = predict_yards_ml(
        model,
        df.iloc[0].to_dict(),
        feature_order=list(PROMOTE_FEATURE_NAMES),
        residual_target=True,
        baseline_mode="market",
    )
    assert 150 <= pred <= 400


def test_train_promote_qb_yards_model_tier_only_override():
    """Ablation override still supports tier-only residual + HP sweep."""
    from app.services.etl.nfl.qb_features import TIER_ONLY_FEATURE_NAMES

    n = 50
    rng = np.random.default_rng(11)
    df = pd.DataFrame(
        {
            name: (
                np.linspace(200, 260, n)
                if name
                in (
                    "tier_yards",
                    "rolling_yards_l3",
                    "pass_yds_line",
                    "season_avg_yards",
                )
                else np.full(n, 1.0 if name == "line_is_real" else 0.0)
            )
            for name in FEATURE_NAMES
        }
    )
    df["season"] = np.concatenate([np.full(25, 2024), np.full(25, 2025)])
    df["week"] = np.arange(1, n + 1)
    y = df["tier_yards"] + 0.2 * df["rolling_yards_l3"] + rng.normal(0, 8, n)
    model, meta = train_promote_qb_yards_model(
        (df, y),
        residual_target=True,
        feature_order=list(TIER_ONLY_FEATURE_NAMES),
        baseline_mode="tier",
    )
    assert meta["baseline_mode"] == "tier"
    assert meta["promote_path"] == "tier_only_residual"
    assert "pass_yds_line" not in meta["features"]
    pred = predict_yards_ml(
        model,
        df.iloc[0].to_dict(),
        feature_order=list(TIER_ONLY_FEATURE_NAMES),
        residual_target=True,
        baseline_mode="tier",
    )
    assert 150 <= pred <= 400


def test_predict_yards_ml_loaded_respects_tier_baseline_mode(monkeypatch):
    class _Stub:
        def predict(self, X):  # noqa: N803
            return np.array([5.0])

    monkeypatch.setattr(qbm, "_MODEL", _Stub())
    monkeypatch.setattr(
        qbm,
        "_METADATA",
        {
            "features": ["tier_yards", "rolling_yards_l3"],
            "residual_target": True,
            "baseline_mode": "tier",
            "target": "residual_actual_minus_baseline",
        },
    )
    monkeypatch.setattr(qbm, "_LOAD_FAILED", False)
    # baseline = tier 250; residual +5 → 255 (ignores pass_yds_line)
    out = qbm.predict_yards_ml_loaded(
        {"tier_yards": 250.0, "rolling_yards_l3": 240.0, "pass_yds_line": 300.0}
    )
    assert out == 255.0


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


def test_blend_ml_with_line_and_select_weight():
    from app.services.etl.nfl.qb_passing_yards_ml import (
        blend_ml_with_line,
        blend_ml_with_line_from_features,
        select_line_blend_weight,
    )

    assert blend_ml_with_line(260.0, pass_yds_line=280.0, w=0.5) == 270.0
    assert blend_ml_with_line(260.0, pass_yds_line=280.0, w=1.0) == 260.0
    assert blend_ml_with_line(260.0, pass_yds_line=280.0, w=0.0) == 280.0
    assert (
        blend_ml_with_line(260.0, pass_yds_line=280.0, w=0.5, line_is_real=False)
        == 260.0
    )
    assert (
        blend_ml_with_line_from_features(
            260.0,
            {
                "tier_yards": 250.0,
                "pass_yds_line": 280.0,
                "line_is_real": 1.0,
                "line_minus_tier": 30.0,
            },
            w=0.25,
        )
        == 275.0
    )

    y = np.array([200.0, 220.0, 240.0, 260.0])
    ml = np.array([210.0, 230.0, 250.0, 270.0])
    line = np.array([200.0, 220.0, 240.0, 260.0])  # perfect line
    real = np.array([True, True, True, False])
    sel = select_line_blend_weight(y_true=y, ml_pred=ml, line_pred=line, real_mask=real)
    assert sel["diagnostic_best_w"] == 0.0  # pure line best diagnostically
    assert sel["selected_w"] == 0.25  # promote excludes w=0
    assert len(sel["candidates"]) == 5


def test_predict_yards_ml_loaded_applies_line_blend(monkeypatch):
    class _Stub:
        def predict(self, X):  # noqa: N803
            return np.array([10.0])

    monkeypatch.setattr(qbm, "_MODEL", _Stub())
    monkeypatch.setattr(
        qbm,
        "_METADATA",
        {
            "features": ["tier_yards", "rolling_yards_l3"],
            "residual_target": True,
            "baseline_mode": "tier",
            "line_blend_w": 0.5,
            "target": "residual_actual_minus_baseline",
        },
    )
    monkeypatch.setattr(qbm, "_LOAD_FAILED", False)
    # tier baseline 250 + residual 10 = 260; blend 0.5 with line 280 → 270
    out = qbm.predict_yards_ml_loaded(
        {
            "tier_yards": 250.0,
            "rolling_yards_l3": 240.0,
            "pass_yds_line": 280.0,
            "line_is_real": 1.0,
            "line_minus_tier": 30.0,
        }
    )
    assert out == 270.0


def test_reinject_pass_yds_line():
    from app.services.etl.nfl.qb_passing_yards_ml import reinject_pass_yds_line

    out = reinject_pass_yds_line(
        {
            "tier_yards": 250.0,
            "pass_yds_line": 250.0,
            "line_minus_tier": 0.0,
            "rolling_yards_l3": 240.0,
        },
        ou_line=275.5,
    )
    assert out["pass_yds_line"] == 275.5
    assert out["line_is_real"] == 1.0
    assert out["line_minus_rolling"] == 35.5
    assert out["line_minus_tier"] == 25.5
    assert out["market_residual_l3"] == -35.5


def test_enrich_ml_without_real_line_stays_dynamic_tier(monkeypatch):
    monkeypatch.setenv("NFL_QB_ML_ENABLED", "1")
    with patch.object(qbm, "predict_yards_ml_loaded", return_value=160.0):
        with patch.object(qbm, "_MODEL", object()):
            with patch.object(
                qbm, "_METADATA", {"target": "residual_actual_minus_baseline"}
            ):
                out = enrich_qb_prediction_for_write(_tier_pred(), season=2024, week=3)
    assert out["predicted_passing_yards"] == 245.0
    assert out["prediction_method"] == "dynamic_starter"


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
                out = enrich_qb_prediction_for_write(
                    _tier_pred(),
                    season=2024,
                    week=3,
                    context={
                        "pass_yds_line": 255.0,
                        "line_is_real": True,
                        "dynamic_tier_yards": 245.0,
                    },
                )
    assert out["predicted_passing_yards"] == 260.0
    assert out["prediction_method"] == "gbm_qb_residual"


def test_local_model_paths_skips_bundled_when_ml_enabled(monkeypatch):
    monkeypatch.setenv("NFL_QB_ML_ENABLED", "1")
    monkeypatch.delenv("NFL_QB_MODEL_LOCAL", raising=False)
    assert qbm._local_model_paths() is None
