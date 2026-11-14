"""Train WNBA totals residual GBM and optionally upload to S3."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore

from app.services.etl.wnba.ml_training.build_totals_dataset import build
from app.services.etl.wnba.ml_training.totals_training_eval import (
    evaluate_holdout_with_segments,
    time_holdout_split,
)
from app.services.etl.wnba.ml_training.validate_totals_model import validate_holdout
from app.services.etl.wnba.totals_ml import (
    MODEL_KEY,
    S3_PREFIX,
    feature_names,
)
from app.services.ml.upload_to_s3 import score_live_pickle, upload_gated_pickle

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 80
HOLDOUT_FRACTION = 0.2

DEFAULT_HYPERPARAMS = {
    "n_estimators": 150,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "min_samples_leaf": 5,
    "random_state": 42,
}


def train_residual_model(
    features_df: pd.DataFrame,
    target: pd.Series,
    game_dates: pd.Series,
    *,
    hyperparams: dict | None = None,
) -> tuple[GradientBoostingRegressor, dict[str, Any]]:
    """Train on time-ordered holdout split; metadata includes full-total MAE."""
    hyperparams = {**DEFAULT_HYPERPARAMS, **(hyperparams or {})}
    train_idx, test_idx = time_holdout_split(game_dates, test_fraction=HOLDOUT_FRACTION)

    if len(test_idx) == 0 or len(train_idx) == 0:
        raise ValueError("insufficient dated rows for time holdout split")

    X_train = features_df.iloc[train_idx]
    X_test = features_df.iloc[test_idx]
    y_train = target.iloc[train_idx]
    y_test = target.iloc[test_idx]

    model = GradientBoostingRegressor(**hyperparams)
    model.fit(X_train, y_train)

    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    heuristic_train = features_df.iloc[train_idx]["heuristic_total"]
    heuristic_test = features_df.iloc[test_idx]["heuristic_total"]
    actual_train = heuristic_train + y_train
    actual_test = heuristic_test + y_test

    holdout = evaluate_holdout_with_segments(
        y_residual=y_test,
        y_residual_pred=y_pred_test,
        heuristic_totals=heuristic_test,
        actual_totals=actual_test,
        market_totals=features_df.iloc[test_idx]["market_total"],
    )

    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": "residual_actual_minus_heuristic",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "split": "time_holdout",
        "holdout_fraction": HOLDOUT_FRACTION,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": list(features_df.columns),
        "hyperparams": hyperparams,
        "train_mae": float(mean_absolute_error(y_train, y_pred_train)),
        "test_mae": float(holdout["residual_mae"]),
        "holdout_mae": float(holdout["residual_mae"]),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, y_pred_train))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
        "holdout": holdout,
        "train_full_total_mae": {
            "heuristic": float(
                mean_absolute_error(actual_train, heuristic_train.to_numpy())
            ),
            "ml": float(
                mean_absolute_error(
                    actual_train.to_numpy(),
                    heuristic_train.to_numpy() + y_pred_train,
                )
            ),
        },
    }
    logger.info(
        "trained %s: train_mae=%.3f holdout_residual_mae=%.3f "
        "holdout_full_mae heuristic=%.3f ml=%.3f",
        MODEL_KEY,
        metadata["train_mae"],
        metadata["holdout_mae"],
        holdout["heuristic_full_total_mae"],
        holdout["ml_full_total_mae"],
    )
    for seg_name, seg in holdout.get("segments", {}).items():
        n_rows = seg.get("n_rows", 0)
        if not n_rows:
            logger.info("holdout segment %s: n=0", seg_name)
            continue
        logger.info(
            "holdout segment %s: n=%d residual_mae=%.3f "
            "full_mae heuristic=%.3f ml=%.3f",
            seg_name,
            n_rows,
            seg["residual_mae"],
            seg["heuristic_full_total_mae"],
            seg["ml_full_total_mae"],
        )
    return model, metadata


def upload_totals_model(
    model: GradientBoostingRegressor,
    metadata: dict[str, Any],
    X_hold: pd.DataFrame,
    y_hold: pd.Series,
) -> dict[str, Any]:
    """Champion-gated upload: replaces the live model only if it is not worse
    on this holdout (residual MAE, which equals full-total MAE)."""
    model_key = f"{S3_PREFIX}/{MODEL_KEY}.pkl"
    return upload_gated_pickle(
        model_key,
        model,
        metadata,
        candidate_metric=float(
            mean_absolute_error(y_hold, model.predict(X_hold))
        ),
        score_champion=score_live_pickle(
            f"{S3_PREFIX}/{MODEL_KEY}_metadata.json", X_hold, y_hold
        ),
    )


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
    skip_gate: bool = False,
) -> dict:
    features_df, target, game_dates, dataset_stats = build(season_start, season_end)
    if features_df.empty or len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
            "dataset_stats": dataset_stats,
        }

    order = feature_names()
    missing = [c for c in order if c not in features_df.columns]
    for col in missing:
        features_df[col] = 0.0
    features_df = features_df[order]

    model, metadata = train_residual_model(features_df, target, game_dates)
    metadata["data_window"] = f"{season_start}..{season_end}"
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
        "dataset_stats": dataset_stats,
    }

    validation = validate_holdout(metadata)
    result["validation"] = validation

    if upload:
        if not skip_gate and not validation["passes_gate"]:
            result["status"] = "gate_failed"
            logger.warning(
                "totals upload blocked: %s (ml_full=%.3f heuristic_full=%.3f "
                "residual=%.3f soft_residual_ceiling=%.3f)",
                validation.get("reason") or validation.get("gate"),
                validation.get("ml_full_total_mae") or float("nan"),
                validation.get("heuristic_full_total_mae") or float("nan"),
                validation.get("mae") or float("nan"),
                validation.get("gate_threshold") or float("nan"),
            )
            return result
        _, test_idx = time_holdout_split(game_dates, test_fraction=HOLDOUT_FRACTION)
        out = upload_totals_model(
            model,
            metadata,
            features_df.iloc[test_idx],
            target.iloc[test_idx],
        )
        result["gate"] = out
        if out["status"] == "rejected_by_champion":
            logger.warning(
                "WNBA totals candidate rejected: holdout MAE %.3f vs live %.3f",
                out["candidate_metric"],
                out["champion_metric"],
            )
            result["status"] = "rejected_by_champion"
        else:
            result["s3_keys"] = {
                k: out[k] for k in ("model_key", "metadata_key", "manifest_key")
            }

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train WNBA totals residual GBM")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument(
        "--skip-gate",
        action="store_true",
        help="Upload even when holdout ML full-total MAE does not beat heuristic",
    )
    args = parser.parse_args()
    out = run(
        season_start=date.fromisoformat(args.start),
        season_end=date.fromisoformat(args.end),
        upload=args.upload,
        skip_gate=args.skip_gate,
    )
    print(out)
    if out.get("status") not in ("ok", "rejected_by_champion"):
        raise SystemExit(1)
