"""Train NBA spread margin XGBoost and optionally upload to S3.

The model replaces the Elo margin in spread_projector, so it is only uploaded
when it beats Elo on the same 20% holdout; the metadata records both MAEs and
_spread_ml_predict refuses any model whose metadata doesn't show the win.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np

from app.services.etl.nba._spread_ml_predict import MIN_TRAINING_ROWS
from app.services.etl.nba.ml_training.build_spread_dataset import build
from app.services.etl.nba.ml_training.train_model import train
from app.services.ml.train_model import split
from app.services.etl.nba.ml_training.upload_to_s3 import upload_spread_model

logger = logging.getLogger(__name__)

# Shallow and regularized: ~2.6k games of a noisy target overfit the prop
# defaults (train MAE 5.4 vs test 11.6).
SPREAD_HYPERPARAMS = {
    "n_estimators": 200,
    "max_depth": 2,
    "learning_rate": 0.03,
    "min_child_weight": 20,
}

# Margins the projector falls back to without a model.
BASELINE_COLUMNS = ("base_margin", "elo_pace_margin")


def baseline_holdout_mae(features_df, target) -> float:
    """Best Elo-only MAE on the same 20% holdout ``train`` uses."""
    _, X_test, _, y_test = split(features_df, target, chronological=True)
    y = np.asarray(y_test, dtype=float)
    return min(
        float(np.mean(np.abs(np.asarray(X_test[c], dtype=float) - y)))
        for c in BASELINE_COLUMNS
    )


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
) -> dict:
    features_df, target = build(season_start, season_end)
    if len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
        }

    model, metadata = train(
        "spread",
        features_df,
        target,
        hyperparams=SPREAD_HYPERPARAMS,
        chronological=True,
    )
    metadata = dict(metadata)
    metadata["baseline_test_mae"] = baseline_holdout_mae(features_df, target)
    metadata["beats_baseline"] = metadata["test_mae"] < metadata["baseline_test_mae"]
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if not metadata["beats_baseline"]:
        logger.warning(
            "NBA spread model does not beat Elo: test_mae=%.3f baseline=%.3f",
            metadata["test_mae"],
            metadata["baseline_test_mae"],
        )
        result["status"] = "below_baseline"
        return result
    if upload:
        result["s3_keys"] = upload_spread_model(model, metadata)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train NBA spread ML model")
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
    if out.get("status") != "ok":
        raise SystemExit(1)
