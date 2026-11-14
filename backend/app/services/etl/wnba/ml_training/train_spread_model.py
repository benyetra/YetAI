"""Train WNBA spread margin XGBoost and optionally upload to S3."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np

from app.services.etl._spread_model import WNBA_CONFIG, margin_to_win_prob
from app.services.etl.wnba._spread_ml_predict import MIN_TRAINING_ROWS
from app.services.etl.wnba.ml_training.build_spread_dataset import build
from app.services.etl.wnba.ml_training.train_model import train
from app.services.etl.wnba.ml_training import upload_to_s3
from app.services.etl.wnba.ml_training.validate_spread_model import validate_holdout
from app.services.ml.train_model import split

logger = logging.getLogger(__name__)


def _holdout_brier(model: Any, features_df, target) -> float:
    """Win-prob Brier on the same 20% holdout split used by ``train``."""
    _, X_test, _, y_test = split(features_df, target, chronological=True)
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

    # Chronological holdout: the builder emits rows in date order.
    model, metadata = train("spread", features_df, target, chronological=True)
    metadata = dict(metadata)
    metadata["data_window"] = f"{season_start}..{season_end}"
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
        # Only replace the live model if it is not worse on this same holdout.
        _, X_test, _, y_test = split(features_df, target, chronological=True)
        out = upload_to_s3.upload_gated(
            "spread",
            model,
            metadata,
            candidate_metric=metadata["test_mae"],
            metric_name="test_mae",
            score_champion=upload_to_s3.live_scorer(
                "spread", X_test, y_test, fill=float("nan")
            ),
        )
        result["gate"] = out
        if out["status"] == "rejected_by_champion":
            logger.warning(
                "WNBA spread candidate rejected: holdout MAE %.3f vs live %.3f",
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
    if out.get("status") not in {"ok", "insufficient_data", "rejected_by_champion"}:
        raise SystemExit(1)
