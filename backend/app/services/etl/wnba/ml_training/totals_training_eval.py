"""Evaluation helpers for WNBA totals residual model training."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error  # type: ignore


def time_holdout_split(
    game_dates: pd.Series,
    *,
    test_fraction: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return train/test index arrays using the last ``test_fraction`` of games by date.

    Rows with identical dates stay in the same split.
    """
    if game_dates.empty:
        return np.array([], dtype=int), np.array([], dtype=int)

    order = np.argsort(game_dates.values)
    unique_dates = sorted({d for d in game_dates.iloc[order].tolist()})
    if len(unique_dates) < 2:
        return order, np.array([], dtype=int)

    cutoff_idx = max(1, int(round(len(unique_dates) * (1.0 - test_fraction))))
    cutoff_idx = min(cutoff_idx, len(unique_dates) - 1)
    cutoff_date = unique_dates[cutoff_idx]

    sorted_dates = game_dates.iloc[order]
    train_mask = sorted_dates < cutoff_date
    test_mask = ~train_mask
    train_idx = order[train_mask.to_numpy()]
    test_idx = order[test_mask.to_numpy()]
    return train_idx, test_idx


def evaluate_holdout(
    *,
    y_residual: pd.Series,
    y_residual_pred: np.ndarray,
    heuristic_totals: pd.Series,
    actual_totals: pd.Series,
) -> dict[str, Any]:
    """Compute residual and full-total MAE for heuristic baseline vs ML."""
    residual_mae = float(mean_absolute_error(y_residual, y_residual_pred))
    ml_totals = heuristic_totals.to_numpy(dtype=float) + y_residual_pred
    actual = actual_totals.to_numpy(dtype=float)
    heuristic = heuristic_totals.to_numpy(dtype=float)

    heuristic_full_mae = float(mean_absolute_error(actual, heuristic))
    ml_full_mae = float(mean_absolute_error(actual, ml_totals))

    return {
        "residual_mae": residual_mae,
        "heuristic_full_total_mae": heuristic_full_mae,
        "ml_full_total_mae": ml_full_mae,
        "ml_beats_heuristic": ml_full_mae < heuristic_full_mae,
        "n_rows": int(len(y_residual)),
    }


def evaluate_holdout_with_segments(
    *,
    y_residual: pd.Series,
    y_residual_pred: np.ndarray,
    heuristic_totals: pd.Series,
    actual_totals: pd.Series,
    market_totals: pd.Series,
) -> dict[str, Any]:
    """Holdout metrics overall and split by presence of ``market_total``."""
    overall = evaluate_holdout(
        y_residual=y_residual,
        y_residual_pred=y_residual_pred,
        heuristic_totals=heuristic_totals,
        actual_totals=actual_totals,
    )
    segments: dict[str, Any] = {}
    market = market_totals.to_numpy(dtype=float)
    for label, mask in (
        ("with_market_total", market > 0),
        ("without_market_total", market <= 0),
    ):
        if not mask.any():
            segments[label] = {"n_rows": 0}
            continue
        segments[label] = evaluate_holdout(
            y_residual=y_residual.iloc[mask],
            y_residual_pred=y_residual_pred[mask],
            heuristic_totals=heuristic_totals.iloc[mask],
            actual_totals=actual_totals.iloc[mask],
        )
    overall["segments"] = segments
    return overall
