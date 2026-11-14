"""End-to-end WNBA prop XGB retrain: dataset → train → MAE gate → champion-gated S3 upload."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
from sklearn.metrics import mean_absolute_error  # type: ignore

from app.services.etl.wnba.ml_training import (
    build_training_dataset,
    train_model,
    upload_to_s3,
    validate_model,
)
from app.services.etl.wnba.ml_training.config import WNBA_ML_CONFIG
from app.services.etl.wnba.prop_calibration import fit_residual_calibration
from app.services.ml.train_model import split
from app.services.ml_model_version import model_version_from_metadata

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 100


def _enrich_metadata(stat_col: str, metadata: dict[str, Any]) -> dict[str, Any]:
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
    if stat_col not in WNBA_ML_CONFIG.supported_stats:
        raise ValueError(
            f"stat {stat_col!r} not supported; "
            f"choose from {WNBA_ML_CONFIG.supported_stats}"
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
            "feature_count": len(features_df.columns) if row_count else 0,
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

    # Chronological: the builder emits rows in date order, so the holdout is
    # games after the ones the model learned from.
    model, metadata = train_model.train(
        stat_col, features_df, target, chronological=True
    )
    metadata = _enrich_metadata(stat_col, metadata)
    metadata["data_window"] = f"{season_start}..{season_end}"

    _, X_hold, _, y_hold = split(features_df, target, chronological=True)
    holdout_preds = model.predict(X_hold)
    holdout_mae = float(mean_absolute_error(y_hold, holdout_preds))
    metadata["holdout_mae"] = holdout_mae

    holdout_actuals = np.asarray(y_hold, dtype=float)
    holdout_lines = np.round(holdout_actuals * 2) / 2
    cal_params = fit_residual_calibration(
        stat_col, holdout_preds, holdout_actuals, holdout_lines
    )
    metadata["prop_calibration"] = cal_params.to_dict()

    # Judge on the holdout only: validating on every row would include the 80%
    # the model trained on.
    validation = validate_model.validate(stat_col, model, X_hold, y_hold)
    metadata["validation"] = validation

    if not validation["passes_gate"]:
        logger.warning(
            "WNBA %s model failed MAE gate: mae=%.3f threshold=%.3f",
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
        # Only replace the live model if it is not worse on this same holdout.
        out = upload_to_s3.upload_gated(
            stat_col,
            model,
            metadata,
            candidate_metric=validation["mae"],
            score_champion=upload_to_s3.live_scorer(stat_col, X_hold, y_hold),
        )
        result["gate"] = out
        if out["status"] == "rejected_by_champion":
            logger.warning(
                "WNBA %s candidate rejected: holdout MAE %.3f vs live %.3f",
                stat_col,
                out["candidate_metric"],
                out["champion_metric"],
            )
            result["status"] = "rejected_by_champion"
        else:
            result["s3_keys"] = {
                k: out[k] for k in ("model_key", "metadata_key", "manifest_key")
            }

    return result
