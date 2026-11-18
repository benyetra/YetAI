"""End-to-end NBA prop XGB retrain: dataset → train → MAE gate → promote gate → S3 upload."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.core import database
from app.services.etl.nba.residual import dataset as residual_dataset
from app.services.etl.nba.ml_training import (
    build_training_dataset,
    train_model,
    upload_to_s3,
    validate_model,
)
from app.services.etl.nba._feature_engineering import FEATURES_VERSION
from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.etl.nba.prop_calibration import fit_time_ordered
from app.services.ml import dataset_cache, promote_gate
from app.services.ml import upload_to_s3 as ml_upload
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


def _load_lines(stat_col: str, start, end):
    with database.engine.connect() as conn:
        return residual_dataset.load_lines(conn, stat_col, start, end)


def holdout_lines(stat_col: str, keys, n_hold: int):
    """Per-holdout-row stored line (NaN when none) and game date, aligned with the
    last ``n_hold`` rows. Never raises: a loading error gives all-NaN lines and the
    error text, which the gate turns into ``no_line_evidence``."""
    keys = list(keys or [])[-n_hold:] if n_hold else []
    if len(keys) != n_hold:  # builder gave no (player_id, game_date) keys
        return np.full(n_hold, np.nan), None, "builder returned no keys for the holdout"
    k = pd.DataFrame(keys, columns=["player_id", "date"])
    k["date"] = pd.to_datetime(k["date"])
    try:
        lines = _load_lines(stat_col, k["date"].min(), k["date"].max())
        lines = lines.assign(player_id=lines["player_id"].astype(k["player_id"].dtype))
        m = k.merge(
            lines[["player_id", "date", "line"]], on=["player_id", "date"], how="left"
        )
        return m["line"].to_numpy(dtype=float), k["date"].to_numpy(), None
    except Exception as exc:
        logger.warning("NBA %s lines unavailable: %s", stat_col, exc)
        return np.full(n_hold, np.nan), k["date"].to_numpy(), str(exc)


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
            NBA_ML_CONFIG.s3_prefix,
            stat_col,
            season_start,
            season_end,
            version=FEATURES_VERSION,
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
    metadata["data_window"] = f"{season_start}..{season_end}"

    _, X_hold, _, y_hold = split(features_df, target, chronological=True)
    holdout_preds = model.predict(X_hold)
    holdout_actuals = y_hold.values
    keys = features_df.attrs.get("keys") or []
    line, hold_dates, line_error = holdout_lines(stat_col, keys, len(X_hold))
    if line_error:
        metadata["line_error"] = line_error
    rounded_lines = np.round(holdout_actuals.astype(float) * 2) / 2
    # Fit on the earlier holdout rows, gate on the later ones (not served yet:
    # NBA_PROP_CALIBRATION_ENABLED stays off).
    cal_params, cal_info = fit_time_ordered(
        stat_col, holdout_preds, holdout_actuals, rounded_lines
    )
    metadata["prop_calibration"] = cal_params.to_dict()
    metadata["prop_calibration_eval"] = cal_info
    logger.info("NBA %s prop calibration (time-ordered): %s", stat_col, cal_info)

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

    # Promote gate: stored-line evidence, no worse than the line, and (with upload)
    # a real gain over the live model on the same rows.
    live_key = f"{NBA_ML_CONFIG.s3_prefix}/xgb_{stat_col}.pkl"
    champ = (
        ml_upload.live_prop_predictions(NBA_ML_CONFIG, stat_col, X_hold)
        if upload
        else None
    )  # None: no live model (first upload) or not uploading; a failure raises
    gate = promote_gate.promote_gate(
        holdout_preds, holdout_actuals, line, dates=hold_dates, champion_pred=champ
    )
    metadata["promote_gate"] = gate
    metadata["line_comparison"] = gate["lined"]
    logger.info(promote_gate.format_gate_line("NBA " + stat_col, gate))
    outcome_extra = {
        "stat": stat_col,
        "candidate_version": metadata.get("model_version"),
        "data_window": metadata["data_window"],
    }
    if upload:
        promote_gate.record_outcome(live_key, gate, extra=outcome_extra)

    result: dict[str, Any] = {
        "status": "ok",
        "stat": stat_col,
        "rows": row_count,
        "metadata": metadata,
        "validation": validation,
        "upload": upload,
    }
    if not gate["passes"]:
        result["status"] = gate["status"]
        result["reason"] = gate["reason"]
        return result

    if upload:
        # Same rows for both sides, so gated_upload's strict check agrees with the gate.
        cb = gate["champion"]
        comparable = bool(cb and cb["comparable"])

        def score_champion(_body: bytes) -> float:
            if not comparable:
                raise ValueError("champion not comparable on the lined holdout rows")
            return cb["champion_mae"]

        out = upload_to_s3.upload_gated(
            stat_col,
            model,
            metadata,
            candidate_metric=(
                cb["candidate_mae"] if comparable else gate["lined"]["model_mae"]
            ),
            score_champion=score_champion,
            line_gate=gate,
            manifest_extra={"line_comparison": gate["lined"]},
        )
        result["gate"] = out
        # the gate passed; record what the upload itself did (e.g. unchanged window)
        promote_gate.record_outcome(
            live_key, gate, extra={**outcome_extra, "upload_status": out["status"]}
        )
        if out["status"] == "rejected_by_champion":
            logger.warning(
                "NBA %s candidate rejected: holdout MAE %.3f vs live %s (%s)",
                stat_col,
                out["candidate_metric"],
                out.get("champion_metric"),
                out.get("reason"),
            )
            result["status"] = "rejected_by_champion"
        else:
            result["s3_keys"] = {
                k: out[k] for k in ("model_key", "metadata_key", "manifest_key")
            }

    return result
