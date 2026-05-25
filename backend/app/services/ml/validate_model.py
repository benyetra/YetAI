"""Validate a trained prop model against a holdout dataset.

Hard gate thresholds are league-specific via ``LeagueMLConfig.mae_gate``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore

from app.services.ml.config import LeagueMLConfig

logger = logging.getLogger(__name__)


def validate(
    config: LeagueMLConfig,
    stat_col: str,
    model: xgb.XGBRegressor,
    features_df: pd.DataFrame,
    target: pd.Series,
) -> dict[str, Any]:
    if stat_col not in config.mae_gate:
        raise ValueError(f"no gate defined for stat {stat_col}")

    y_pred = model.predict(features_df)
    residuals = y_pred - target.values
    mae = float(mean_absolute_error(target, y_pred))
    rmse = float(np.sqrt(mean_squared_error(target, y_pred)))

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

    gate_threshold = config.mae_gate[stat_col]
    passes_gate = mae <= gate_threshold
    return {
        "stat": stat_col,
        "passes_gate": passes_gate,
        "gate_threshold": gate_threshold,
        "mae": mae,
        "rmse": rmse,
        "residual_mean": float(residuals.mean()),
        "residual_std": float(residuals.std()),
        "calibration": calibration,
        "n_validation_rows": int(len(features_df)),
    }
