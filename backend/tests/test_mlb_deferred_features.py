"""Unit tests for MLB game model deferred feature coverage and promotion."""

import pandas as pd
import pytest

from app.services.etl.mlb.game_model import (
    DEFERRED_FEATURE_COLS,
    DEFERRED_PROMOTION_MIN_NON_NEUTRAL_PCT,
    FEATURE_COLS,
    FEATURE_NEUTRAL_VALUES,
    attach_feature_cols_to_ensemble,
    columns_to_promote_from_deferred_coverage,
    deferred_feature_coverage_report,
    ensemble_feature_cols,
    expanded_feature_cols,
    feature_coverage_report,
    promote_deferred_features,
)
from app.services.etl.mlb.game_model_eval import deferred_retrain_recommended


def _training_frame(n: int, **overrides) -> pd.DataFrame:
    """Minimal training-shaped frame with neutral deferred defaults."""
    rows = []
    for _ in range(n):
        row = {col: FEATURE_NEUTRAL_VALUES[col] for col in DEFERRED_FEATURE_COLS}
        row.update({col: 0.0 for col in FEATURE_COLS if col not in row})
        rows.append(row)
    df = pd.DataFrame(rows)
    for key, val in overrides.items():
        df[key] = val
    return df


def test_deferred_feature_coverage_report_all_neutral():
    df = _training_frame(100)
    report = deferred_feature_coverage_report(df)
    assert report["n_rows"] == 100
    assert report["deferred_columns"] == list(DEFERRED_FEATURE_COLS)
    for row in report["features"]:
        assert row["pct_non_neutral"] == pytest.approx(0.0)
        assert row["pct_at_neutral_default"] == pytest.approx(1.0)


def test_deferred_feature_coverage_report_rest_mostly_non_neutral():
    n = 100
    df = _training_frame(n, rest_differential=[0.0] * 10 + [2.0] * 90)
    report = deferred_feature_coverage_report(df)
    rest = next(r for r in report["features"] if r["feature"] == "rest_differential")
    assert rest["pct_non_neutral"] == pytest.approx(0.9)
    assert rest["pct_at_neutral_default"] == pytest.approx(0.1)


def test_columns_to_promote_from_deferred_coverage_threshold():
    coverage = {
        "features": [
            {"feature": "rest_differential", "pct_non_neutral": 0.85},
            {"feature": "home_field", "pct_non_neutral": 0.0},
            {"feature": "umpire_run_adj", "pct_at_neutral_default": 0.15},
        ]
    }
    promoted = columns_to_promote_from_deferred_coverage(coverage, threshold=0.80)
    assert "rest_differential" in promoted
    assert "umpire_run_adj" in promoted
    assert "home_field" not in promoted


def test_columns_to_promote_derives_non_neutral_from_default_pct():
    coverage = {
        "features": [
            {"feature": "away_ttop_adj", "pct_at_neutral_default": 0.10},
        ]
    }
    promoted = columns_to_promote_from_deferred_coverage(coverage, threshold=0.80)
    assert promoted == ["away_ttop_adj"]


def test_promote_deferred_features_expanded_cols():
    df = _training_frame(50, rest_differential=[3.0] * 50)
    result = promote_deferred_features(df, threshold=0.80)
    assert "rest_differential" in result["promoted"]
    assert result["expanded_feature_cols"] == expanded_feature_cols(
        ["rest_differential"]
    )
    assert "rest_differential" not in result["remaining_deferred"]


def test_expanded_feature_cols_preserves_baseline_order():
    expanded = expanded_feature_cols(["rest_differential", "home_field"])
    assert expanded[: len(FEATURE_COLS)] == FEATURE_COLS
    assert expanded[-2:] == ["rest_differential", "home_field"]


def test_feature_coverage_report_include_deferred():
    df = _training_frame(20)
    report = feature_coverage_report(df, include_deferred=True)
    names = {r["feature"] for r in report["features"]}
    assert set(DEFERRED_FEATURE_COLS).issubset(names)
    assert set(FEATURE_COLS).issubset(names)


def test_deferred_retrain_recommended_brier_lift():
    baseline = {
        "mean_test_win_brier_model": 0.250,
        "mean_test_win_ml_accuracy_model": 0.52,
    }
    expanded = {
        "mean_test_win_brier_model": 0.244,
        "mean_test_win_ml_accuracy_model": 0.52,
    }
    decision = deferred_retrain_recommended(
        baseline,
        expanded,
        brier_lift_min=0.005,
        ml_accuracy_lift_min=0.01,
    )
    assert decision["brier_lift_vs_baseline"] == pytest.approx(0.006)
    assert decision["retrain_recommended"] is True
    assert decision["meets_brier_threshold"] is True


def test_deferred_retrain_recommended_no_lift():
    baseline = {
        "mean_test_win_brier_model": 0.250,
        "mean_test_win_ml_accuracy_model": 0.55,
    }
    expanded = {
        "mean_test_win_brier_model": 0.249,
        "mean_test_win_ml_accuracy_model": 0.551,
    }
    decision = deferred_retrain_recommended(
        baseline,
        expanded,
        brier_lift_min=0.005,
        ml_accuracy_lift_min=0.01,
    )
    assert decision["retrain_recommended"] is False


def test_all_deferred_cols_have_neutral_values():
    for col in DEFERRED_FEATURE_COLS:
        assert col in FEATURE_NEUTRAL_VALUES


def test_ensemble_feature_cols_round_trip():
    ensemble = {"xgboost": object(), "weights": {"xgboost": 1.0}}
    attach_feature_cols_to_ensemble(ensemble, ["a", "b"])
    assert ensemble_feature_cols(ensemble) == ["a", "b"]
    assert ensemble_feature_cols({}) == FEATURE_COLS
