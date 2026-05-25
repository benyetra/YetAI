"""Train one XGBoost regressor for a given prop.

Splits the input data 80/20 train/holdout, fits, returns the model + metadata
dict. Caller (validate_model + upload_to_s3) decides whether to ship.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
from sklearn.model_selection import train_test_split  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_HYPERPARAMS = {
    "n_estimators": 400,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_alpha": 0.5,
    "reg_lambda": 1.0,
    "random_state": 42,
    "tree_method": "hist",
}


def train(
    stat_col: str,
    features_df: pd.DataFrame,
    target: pd.Series,
    *,
    hyperparams: dict | None = None,
) -> tuple[xgb.XGBRegressor, dict[str, Any]]:
    hyperparams = {**DEFAULT_HYPERPARAMS, **(hyperparams or {})}

    X_train, X_test, y_train, y_test = train_test_split(
        features_df, target, test_size=0.2, random_state=42
    )

    model = xgb.XGBRegressor(**hyperparams)
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    metadata = {
        "stat": stat_col,
        "trained_at": datetime.utcnow().isoformat(),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": list(features_df.columns),
        "hyperparams": hyperparams,
        "train_mae": float(mean_absolute_error(y_train, y_pred_train)),
        "test_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, y_pred_train))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
    }
    logger.info(
        "trained %s: train_mae=%.3f test_mae=%.3f",
        stat_col,
        metadata["train_mae"],
        metadata["test_mae"],
    )
    return model, metadata
