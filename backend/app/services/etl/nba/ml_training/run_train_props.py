"""End-to-end NBA prop XGB retrain: dataset → train → MAE gate → optional S3 upload."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
from sklearn.model_selection import train_test_split  # type: ignore

from app.services.etl.nba.ml_training import (
    build_training_dataset,
    train_model,
    upload_to_s3,
    validate_model,
)
from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.etl.nba.prop_calibration import fit_residual_calibration
from app.services.ml_model_version import model_version_from_metadata

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 100


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
) -> dict[str, Any]:
    """Build dataset, train, validate MAE gate, optionally upload to S3."""
    if stat_col not in NBA_ML_CONFIG.supported_stats:
        raise ValueError(
            f"stat {stat_col!r} not supported; "
            f"choose from {NBA_ML_CONFIG.supported_stats}"
        )

    features_df, target = build_training_dataset.build(
        stat_col, season_start, season_end
    )
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

    model, metadata = train_model.train(stat_col, features_df, target)
    metadata = _enrich_metadata(stat_col, metadata)

    _, X_hold, _, y_hold = train_test_split(
        features_df, target, test_size=0.2, random_state=42
    )
    holdout_preds = model.predict(X_hold)
    holdout_actuals = y_hold.values
    holdout_lines = np.round(holdout_actuals.astype(float) * 2) / 2
    cal_params = fit_residual_calibration(
        stat_col, holdout_preds, holdout_actuals, holdout_lines
    )
    metadata["prop_calibration"] = cal_params.to_dict()

    validation = validate_model.validate(stat_col, model, features_df, target)
    metadata["validation"] = validation

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
