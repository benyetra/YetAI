"""Walk-forward WNBA prop model evaluation on a holdout date window.

Trains on ``[train_start, holdout_start)`` and scores MAE on
``[holdout_start, holdout_end]``. Use before promoting enriched features.

Example::

    cd backend && PYTHONPATH=. .venv/bin/python \\
        -m app.services.etl.wnba.ml_training.prop_model_eval \\
        --stat points --train-start 2024-05-01 --holdout-start 2025-05-01 \\
        --holdout-end 2025-10-01
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from typing import Any

from sklearn.metrics import mean_absolute_error  # type: ignore

from app.services.etl.wnba.ml_training import build_training_dataset, train_model
from app.services.etl.wnba.ml_training.config import WNBA_ML_CONFIG

logger = logging.getLogger(__name__)


def evaluate(
    stat_col: str,
    *,
    train_start: date,
    holdout_start: date,
    holdout_end: date,
) -> dict[str, Any]:
    if stat_col not in WNBA_ML_CONFIG.supported_stats:
        raise ValueError(f"unsupported stat: {stat_col}")

    train_end = holdout_start.fromordinal(holdout_start.toordinal() - 1)
    X_train, y_train = build_training_dataset.build(stat_col, train_start, train_end)
    X_hold, y_hold = build_training_dataset.build(stat_col, holdout_start, holdout_end)

    if len(X_train) < 50 or len(X_hold) < 20:
        return {
            "status": "insufficient_data",
            "stat": stat_col,
            "train_rows": len(X_train),
            "holdout_rows": len(X_hold),
        }

    model, metadata = train_model.train(stat_col, X_train, y_train)
    preds = model.predict(X_hold)
    holdout_mae = float(mean_absolute_error(y_hold, preds))
    gate = WNBA_ML_CONFIG.mae_gate[stat_col]

    return {
        "status": "ok",
        "stat": stat_col,
        "train_window": {
            "start": train_start.isoformat(),
            "end": train_end.isoformat(),
            "rows": len(X_train),
        },
        "holdout_window": {
            "start": holdout_start.isoformat(),
            "end": holdout_end.isoformat(),
            "rows": len(X_hold),
        },
        "feature_count": len(X_train.columns),
        "features": list(X_train.columns),
        "holdout_mae": holdout_mae,
        "gate_threshold": gate,
        "passes_gate": holdout_mae <= gate,
        "train_test_mae": metadata.get("test_mae"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate WNBA prop model on holdout")
    parser.add_argument("--stat", required=True, choices=WNBA_ML_CONFIG.supported_stats)
    parser.add_argument("--train-start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--holdout-start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--holdout-end", required=True, help="YYYY-MM-DD")
    args = parser.parse_args(argv)

    result = evaluate(
        args.stat,
        train_start=date.fromisoformat(args.train_start),
        holdout_start=date.fromisoformat(args.holdout_start),
        holdout_end=date.fromisoformat(args.holdout_end),
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
