"""Validate a trained WNBA prop model against the 2025 holdout season.

Returns dict with:
    {
        "passes_gate": bool,
        "mae": float,
        "rmse": float,
        "residual_mean": float,
        "residual_std": float,
        "calibration": list[dict],  # per-bucket residual stats
    }

Hard gate thresholds (spec-locked, no goalpost moving):
    points  <= 4.5
    assists <= 1.5
    rebounds <= 2.0
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore

logger = logging.getLogger(__name__)

MAE_GATE: dict[str, float] = {
    "points": 4.5,
    "assists": 1.5,
    "rebounds": 2.0,
}


def validate(
    stat_col: str,
    model: xgb.XGBRegressor,
    features_df: pd.DataFrame,
    target: pd.Series,
) -> dict[str, Any]:
    if stat_col not in MAE_GATE:
        raise ValueError(f"no gate defined for stat {stat_col}")

    y_pred = model.predict(features_df)
    residuals = y_pred - target.values
    mae = float(mean_absolute_error(target, y_pred))
    rmse = float(np.sqrt(mean_squared_error(target, y_pred)))

    # Calibration: bucket by projected value, check residual mean.
    df = pd.DataFrame({"pred": y_pred, "actual": target.values, "residual": residuals})
    df["bucket"] = pd.cut(df["pred"], bins=5)
    calibration = [
        {
            "bucket": str(b),
            "count": int(g.shape[0]),
            "residual_mean": float(g["residual"].mean()),
            "residual_std": float(g["residual"].std()),
        }
        for b, g in df.groupby("bucket", observed=False)
    ]

    passes_gate = mae <= MAE_GATE[stat_col]
    return {
        "stat": stat_col,
        "passes_gate": passes_gate,
        "gate_threshold": MAE_GATE[stat_col],
        "mae": mae,
        "rmse": rmse,
        "residual_mean": float(residuals.mean()),
        "residual_std": float(residuals.std()),
        "calibration": calibration,
        "n_validation_rows": int(len(features_df)),
    }
