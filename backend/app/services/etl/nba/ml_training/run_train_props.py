"""End-to-end NBA prop XGB retrain: dataset → train → MAE gate → optional S3 upload."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np

from app.services.etl.nba.ml_training import (
    build_training_dataset,
    train_model,
    upload_to_s3,
    validate_model,
)
from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.etl.nba.prop_calibration import fit_residual_calibration
from app.services.ml import dataset_cache
from app.services.ml.train_model import split
from app.services.ml_model_version import model_version_from_metadata

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 100

# Shallow and regularized: on later games (chronological holdout, 19k rows) the
# shipped depth-5 / 400-tree defaults lost to a plain recent average, while this
# setting beat the default for points, rebounds and assists
# (4.805 vs 4.919, 1.963 vs 1.993, 1.420 vs 1.453 MAE).
PROP_HYPERPARAMS = {
    "max_depth": 2,
    "n_estimators": 300,
    "learning_rate": 0.03,
    "min_child_weight": 50,
}

# The model must beat a naive "recent average" guess on games it never saw.
NAIVE_WINDOWS = (5, 10, 20)


def naive_holdout_mae(stat_col: str, X_hold, y_hold) -> float | None:
    """Best MAE of a player's 5/10/20-game average on the holdout rows where
    all three averages exist (0 means too little history)."""
    cols = [f"{stat_col}_avg_{w}" for w in NAIVE_WINDOWS]
    if any(c not in X_hold.columns for c in cols):
        return None
    usable = (X_hold[cols] > 0).all(axis=1)
    if not usable.any():
        return None
    y = np.asarray(y_hold, dtype=float)[usable.to_numpy()]
    return min(
        float(np.mean(np.abs(np.asarray(X_hold.loc[usable, c], dtype=float) - y)))
        for c in cols
    )


def _enrich_metadata(stat_col: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Normalize keys expected by ``_ml_predict`` and promotion tooling."""
    out = dict(metadata)
    features = out.get("features") or out.get("feature_names")
    if features:
        out["features"] = list(features)
        out["feature_names"] = list(features)
    if "holdout_mae" not in out and out.get("test_mae") is not None:
        out["holdout_mae"] = out["test_mae"]
    if not out.get("model_version"):
        out["model_version"] = model_version_from_metadata(out, prefix="xgb")
    out["stat"] = stat_col
    return out


def run(
    stat_col: str,
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
    dry_run: bool = False,
    cache: bool = False,
) -> dict[str, Any]:
    """Build dataset, train, validate MAE gate, optionally upload to S3."""
    if stat_col not in NBA_ML_CONFIG.supported_stats:
        raise ValueError(
            f"stat {stat_col!r} not supported; "
            f"choose from {NBA_ML_CONFIG.supported_stats}"
        )

    features_df = None
    if cache:
        key = dataset_cache.cache_key(
            NBA_ML_CONFIG.s3_prefix, stat_col, season_start, season_end
        )
        hit = dataset_cache.load(key)
        if hit is not None:
            features_df, target = hit
    if features_df is None:
        features_df, target = build_training_dataset.build(
            stat_col, season_start, season_end
        )
        if cache:
            dataset_cache.save(key, features_df, target)
    row_count = len(features_df)

    if dry_run:
        return {
            "status": "dry_run",
            "stat": stat_col,
            "rows": row_count,
            "min_required": MIN_TRAINING_ROWS,
            "season_start": season_start.isoformat(),
            "season_end": season_end.isoformat(),
            "upload": upload,
        }

    if row_count < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "stat": stat_col,
            "rows": row_count,
            "min_required": MIN_TRAINING_ROWS,
            "season_start": season_start.isoformat(),
            "season_end": season_end.isoformat(),
        }

    model, metadata = train_model.train(
        stat_col,
        features_df,
        target,
        hyperparams=PROP_HYPERPARAMS,
        chronological=True,
    )
    metadata = _enrich_metadata(stat_col, metadata)

    _, X_hold, _, y_hold = split(features_df, target, chronological=True)
    holdout_preds = model.predict(X_hold)
    holdout_actuals = y_hold.values
    holdout_lines = np.round(holdout_actuals.astype(float) * 2) / 2
    cal_params = fit_residual_calibration(
        stat_col, holdout_preds, holdout_actuals, holdout_lines
    )
    metadata["prop_calibration"] = cal_params.to_dict()

    # Judge on the holdout only: validating on every row would include the 80%
    # the model trained on.
    validation = validate_model.validate(stat_col, model, X_hold, y_hold)
    metadata["validation"] = validation
    naive_mae = naive_holdout_mae(stat_col, X_hold, y_hold)
    if naive_mae is not None:
        usable = (X_hold[[f"{stat_col}_avg_{w}" for w in NAIVE_WINDOWS]] > 0).all(
            axis=1
        )
        model_mae = float(
            np.mean(
                np.abs(
                    model.predict(X_hold[usable])
                    - np.asarray(y_hold)[usable.to_numpy()]
                )
            )
        )
        metadata["naive_holdout_mae"] = naive_mae
        metadata["model_mae_vs_naive"] = model_mae
        metadata["beats_naive"] = model_mae < naive_mae
    else:
        metadata["beats_naive"] = True  # no baseline columns to compare against

    if not metadata["beats_naive"]:
        logger.warning(
            "NBA %s model does not beat the recent-average baseline: %.3f vs %.3f",
            stat_col,
            metadata["model_mae_vs_naive"],
            metadata["naive_holdout_mae"],
        )
        return {
            "status": "gate_failed",
            "stat": stat_col,
            "rows": row_count,
            "metadata": metadata,
            "validation": validation,
            "reason": "does_not_beat_naive_baseline",
        }

    if not validation["passes_gate"]:
        logger.warning(
            "NBA %s model failed MAE gate: mae=%.3f threshold=%.3f",
            stat_col,
            validation["mae"],
            validation["gate_threshold"],
        )
        return {
            "status": "gate_failed",
            "stat": stat_col,
            "rows": row_count,
            "metadata": metadata,
            "validation": validation,
        }

    result: dict[str, Any] = {
        "status": "ok",
        "stat": stat_col,
        "rows": row_count,
        "metadata": metadata,
        "validation": validation,
        "upload": upload,
    }

    if upload:
        keys = upload_to_s3.upload(stat_col, model, metadata)
        result["s3_keys"] = keys

    return result
