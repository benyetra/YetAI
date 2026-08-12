"""Smoke tests for prod QB eval promote gate + ablation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_passing_yards_ml import select_line_blend_weight
from scripts.nfl_prod_qb_eval import (
    _PROMOTE_LIFT,
    _line_pred_row,
    _mae,
    _market_baseline_row,
    run_holdout_ablations,
)


def test_promote_gate_is_ten_percent():
    assert _PROMOTE_LIFT == 0.10


def test_mae_helper():
    assert abs(_mae(np.array([10.0, 20.0]), np.array([12.0, 18.0])) - 2.0) < 1e-9


def test_select_line_blend_weight_prefers_better_mae():
    y = np.array([100.0, 200.0, 300.0])
    ml = np.array([140.0, 240.0, 340.0])
    line = np.array([100.0, 200.0, 300.0])
    real = np.array([True, True, True])
    sel = select_line_blend_weight(y_true=y, ml_pred=ml, line_pred=line, real_mask=real)
    # Diagnostic may pick pure line; promote wire-up excludes w=0.
    assert sel["diagnostic_best_w"] == 0.0
    assert sel["selected_w"] == 0.25
    assert sel["min_w_for_promote"] == 0.25


def test_market_and_line_baseline_helpers():
    feats = {
        "tier_yards": 250.0,
        "pass_yds_line": 270.0,
        "line_minus_tier": 20.0,
        "line_is_real": 1.0,
    }
    assert _market_baseline_row(feats, tier=250.0) == 260.0
    assert _line_pred_row(feats, tier=250.0, real_line=272.0) == 272.0
    assert _line_pred_row(feats, tier=250.0, real_line=None) == 270.0


def test_run_holdout_ablations_smoke():
    from app.services.etl.nfl.qb_features import FEATURE_NAMES

    n_train, n_test = 40, 20
    rng = np.random.default_rng(0)

    def _frame(n: int, season: int) -> pd.DataFrame:
        base = {name: np.zeros(n) for name in FEATURE_NAMES}
        base["tier_yards"] = np.linspace(200, 260, n)
        base["pass_yds_line"] = np.linspace(205, 265, n)
        base["line_minus_tier"] = base["pass_yds_line"] - base["tier_yards"]
        base["line_is_real"] = np.ones(n)
        base["season"] = np.full(n, season)
        base["week"] = np.arange(1, n + 1)
        base["rolling_yards_l3"] = base["tier_yards"] + rng.normal(0, 5, n)
        return pd.DataFrame(base)

    X_train = _frame(n_train, 2024)
    X_test = _frame(n_test, 2025)
    y_train = pd.Series(X_train["tier_yards"] + rng.normal(0, 8, n_train))
    y_test = (X_test["tier_yards"] + rng.normal(0, 8, n_test)).to_numpy()
    tier_test = X_test["tier_yards"].to_numpy()
    static_tier_test = tier_test.copy()
    meta_test = pd.DataFrame(
        {
            "pass_yds_line_real": X_test["pass_yds_line"].to_numpy(),
            "season": np.full(n_test, 2025),
            "week": np.arange(1, n_test + 1),
        }
    )
    out = run_holdout_ablations(
        X_train=X_train,
        y_train=y_train,
        X_test=X_test,
        y_test=y_test,
        meta_test=meta_test,
        tier_test=tier_test,
        static_tier_test=static_tier_test,
    )
    for key in (
        "dynamic_tier",
        "static_tier",
        "market_baseline_0_5_tier_line",
        "line_only",
        "v5_features_market_residual",
        "v6_features_market_residual",
        "tier_only_residual",
        "tier_only_promote_sweep",
        "tier_only_residual_shallow",
        "tier_only_residual_strong_reg",
        "summary",
    ):
        assert key in out
    assert out["v6_features_market_residual"]["n_train"] == n_train
    assert out["v6_features_market_residual"]["fit_full"] is True
    assert out["tier_only_promote_sweep"]["fit_full"] is True
    assert out["tier_only_promote_sweep"]["baseline_mode"] == "tier"
    assert out["summary"].get("tier_only_lift_vs_dynamic_tier") is not None
