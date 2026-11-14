"""Train NBA totals residual GBM and optionally upload to S3."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
from sklearn.model_selection import train_test_split  # type: ignore

from app.services.etl.nba.ml_training.build_totals_dataset import build
from app.services.etl.nba.totals_ml import (
    MODEL_KEY,
    S3_PREFIX,
    feature_names,
)
from app.services.ml.upload_to_s3 import score_live_pickle, upload_gated_pickle

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 80

DEFAULT_HYPERPARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "random_state": 42,
}


def train_residual_model(
    features_df,
    target,
    *,
    hyperparams: dict | None = None,
) -> tuple[GradientBoostingRegressor, dict[str, Any]]:
    hyperparams = {**DEFAULT_HYPERPARAMS, **(hyperparams or {})}
    X_train, X_test, y_train, y_test = train_test_split(
        features_df, target, test_size=0.2, random_state=42
    )
    model = GradientBoostingRegressor(**hyperparams)
    model.fit(X_train, y_train)

    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": "residual_actual_minus_heuristic",
        "trained_at": datetime.utcnow().isoformat(),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": list(features_df.columns),
        "hyperparams": hyperparams,
        "train_mae": float(mean_absolute_error(y_train, y_pred_train)),
        "test_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "holdout_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, y_pred_train))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
    }
    logger.info(
        "trained %s: train_mae=%.3f test_mae=%.3f",
        MODEL_KEY,
        metadata["train_mae"],
        metadata["test_mae"],
    )
    return model, metadata


def upload_totals_model(
    model: GradientBoostingRegressor,
    metadata: dict[str, Any],
    X_hold,
    y_hold,
) -> dict[str, Any]:
    """Champion-gated upload: replaces the live model only if it is not worse
    on this holdout (residual MAE, which equals full-total MAE)."""
    model_key = f"{S3_PREFIX}/{MODEL_KEY}.pkl"
    return upload_gated_pickle(
        model_key,
        model,
        metadata,
        candidate_metric=float(mean_absolute_error(y_hold, model.predict(X_hold))),
        score_champion=score_live_pickle(
            f"{S3_PREFIX}/{MODEL_KEY}_metadata.json", X_hold, y_hold
        ),
    )


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
) -> dict:
    features_df, target = build(season_start, season_end)
    if features_df.empty or len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
        }

    # Ensure stable column order for inference
    order = feature_names()
    missing = [c for c in order if c not in features_df.columns]
    for col in missing:
        features_df[col] = 0.0
    features_df = features_df[order]

    model, metadata = train_residual_model(features_df, target)
    metadata["data_window"] = f"{season_start}..{season_end}"
    result = {"status": "ok", "metadata": metadata, "rows": len(features_df)}
    if upload:
        _, X_test, _, y_test = train_test_split(
            features_df, target, test_size=0.2, random_state=42
        )
        out = upload_totals_model(model, metadata, X_test, y_test)
        result["gate"] = out
        if out["status"] == "rejected_by_champion":
            logger.warning(
                "NBA totals candidate rejected: holdout MAE %.3f vs live %.3f",
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

    parser = argparse.ArgumentParser(description="Train NBA totals residual GBM")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    out = run(
        season_start=date.fromisoformat(args.start),
        season_end=date.fromisoformat(args.end),
        upload=args.upload,
    )
    print(out)
    if out.get("status") not in ("ok", "rejected_by_champion"):
        raise SystemExit(1)
