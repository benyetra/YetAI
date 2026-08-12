"""Tests for WNBA totals training evaluation helpers."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.services.etl.wnba.ml_training.totals_training_eval import (
    evaluate_holdout,
    evaluate_holdout_with_segments,
    time_holdout_split,
)
from app.services.etl.wnba.ml_training.validate_totals_model import validate_holdout


def test_time_holdout_split_uses_last_fraction_by_date():
    dates = pd.Series(
        [date(2024, 5, 1), date(2024, 5, 2), date(2024, 6, 1), date(2024, 6, 2)]
    )
    train_idx, test_idx = time_holdout_split(dates, test_fraction=0.5)
    assert len(train_idx) == 2
    assert len(test_idx) == 2
    assert dates.iloc[train_idx].max() < dates.iloc[test_idx].min()


def test_evaluate_holdout_reports_full_total_mae():
    y = pd.Series([2.0, -1.0, 0.5])
    pred = np.array([1.5, -0.5, 0.0])
    heuristic = pd.Series([160.0, 170.0, 165.0])
    actual = heuristic + y

    metrics = evaluate_holdout(
        y_residual=y,
        y_residual_pred=pred,
        heuristic_totals=heuristic,
        actual_totals=actual,
    )
    assert metrics["residual_mae"] < 1.0
    assert metrics["ml_full_total_mae"] <= metrics["heuristic_full_total_mae"]


def test_validate_holdout_passes_when_ml_beats_heuristic():
    meta = {
        "holdout": {
            "residual_mae": 14.1,
            "ml_full_total_mae": 14.1,
            "heuristic_full_total_mae": 15.0,
            "ml_beats_heuristic": True,
        }
    }
    out = validate_holdout(meta)
    assert out["passes_gate"] is True
    assert out["gate"] == "ml_beats_heuristic_full_total_mae"
    assert out["reason"] is None


def test_validate_holdout_fails_when_ml_worse_than_heuristic():
    meta = {
        "holdout": {
            "residual_mae": 14.1,
            "ml_full_total_mae": 15.5,
            "heuristic_full_total_mae": 15.0,
            "ml_beats_heuristic": False,
        }
    }
    out = validate_holdout(meta)
    assert out["passes_gate"] is False
    assert out["reason"] == "ml_full_total_mae_not_better_than_heuristic"


def test_validate_holdout_fails_when_full_total_metrics_missing():
    meta = {"holdout": {"residual_mae": 0.8}}
    out = validate_holdout(meta)
    assert out["passes_gate"] is False
    assert out["reason"] == "missing_holdout_full_total_mae"


def test_evaluate_holdout_with_segments_splits_on_market_total():
    y = pd.Series([2.0, -1.0, 0.5, 3.0])
    pred = np.array([1.5, -0.5, 0.0, 2.0])
    heuristic = pd.Series([160.0, 170.0, 165.0, 168.0])
    actual = heuristic + y
    market = pd.Series([165.0, 0.0, 170.0, 0.0])

    metrics = evaluate_holdout_with_segments(
        y_residual=y,
        y_residual_pred=pred,
        heuristic_totals=heuristic,
        actual_totals=actual,
        market_totals=market,
    )
    assert metrics["n_rows"] == 4
    assert metrics["segments"]["with_market_total"]["n_rows"] == 2
    assert metrics["segments"]["without_market_total"]["n_rows"] == 2
    assert metrics["segments"]["with_market_total"]["residual_mae"] > 0
