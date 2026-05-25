"""WNBA prop model validation — thin wrapper over shared ML package."""

from __future__ import annotations

from typing import Any

import pandas as pd
import xgboost as xgb

from app.services.etl.wnba.ml_training.config import WNBA_ML_CONFIG
from app.services.ml import validate_model as _shared

# Backward-compatible module-level gates (tests patch this dict).
MAE_GATE = WNBA_ML_CONFIG.mae_gate


def validate(
    stat_col: str,
    model: xgb.XGBRegressor,
    features_df: pd.DataFrame,
    target: pd.Series,
) -> dict[str, Any]:
    config = WNBA_ML_CONFIG
    if MAE_GATE is not config.mae_gate:
        from dataclasses import replace

        config = replace(config, mae_gate=dict(MAE_GATE))
    return _shared.validate(config, stat_col, model, features_df, target)
