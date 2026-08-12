"""Train WNBA spread margin XGBoost and optionally upload to S3."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
from sklearn.model_selection import train_test_split  # type: ignore

from app.services.etl._spread_model import WNBA_CONFIG, margin_to_win_prob
from app.services.etl.wnba._spread_ml_predict import MIN_TRAINING_ROWS
from app.services.etl.wnba.ml_training.build_spread_dataset import build
from app.services.etl.wnba.ml_training.train_model import train
from app.services.etl.wnba.ml_training.upload_to_s3 import upload_spread_model
from app.services.etl.wnba.ml_training.validate_spread_model import validate_holdout

logger = logging.getLogger(__name__)


def _holdout_brier(model: Any, features_df, target) -> float:
    """Win-prob Brier on the same 20% holdout split used by ``train``."""
    _, X_test, _, y_test = train_test_split(
        features_df, target, test_size=0.2, random_state=42
    )
    preds = np.asarray(model.predict(X_test), dtype=float)
    actual_win = (np.asarray(y_test, dtype=float) > 0.0).astype(float)
    wp = np.array(
        [margin_to_win_prob(float(m), cfg=WNBA_CONFIG) for m in preds], dtype=float
    )
    return float(np.mean((wp - actual_win) ** 2))


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
    skip_gate: bool = False,
) -> dict:
    features_df, target = build(season_start, season_end)
    if len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
        }

    model, metadata = train("spread", features_df, target)
    metadata = dict(metadata)
    test_brier = _holdout_brier(model, features_df, target)
    metadata["test_brier"] = test_brier
    metadata["holdout"] = {
        "margin_mae": metadata.get("test_mae"),
        "brier": test_brier,
    }

    validation = validate_holdout(metadata)
    metadata["validation"] = validation
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
        "validation": validation,
    }

    if upload:
        if not skip_gate and not validation["passes_gate"]:
            result["status"] = "gate_failed"
            logger.warning(
                "spread upload blocked: mae=%.3f (gate %.3f) brier=%.3f (gate %.3f) "
                "reason=%s",
                validation.get("mae"),
                validation.get("gate_threshold_mae"),
                validation.get("brier"),
                validation.get("gate_threshold_brier"),
                validation.get("reason"),
            )
            return result
        keys = upload_spread_model(model, metadata)
        result["s3_keys"] = keys
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train WNBA spread ML model")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument(
        "--skip-gate",
        action="store_true",
        help="Upload even when holdout MAE/Brier exceeds gates (ops override)",
    )
    args = parser.parse_args()
    out = run(
        season_start=date.fromisoformat(args.start),
        season_end=date.fromisoformat(args.end),
        upload=args.upload,
        skip_gate=args.skip_gate,
    )
    print(out)
    if out.get("status") not in {"ok", "insufficient_data"}:
        raise SystemExit(1)
