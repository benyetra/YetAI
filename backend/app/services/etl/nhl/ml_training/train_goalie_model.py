"""Train NHL goalie saves regressor and optionally upload to S3."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from app.services.etl.nhl.goalie_saves_ml import (
    MODEL_KEY,
    S3_PREFIX,
    feature_names,
    train_goalie_model,
)
from app.services.etl.nhl.ml_training._gated import upload_gated_model
from app.services.etl.nhl.ml_training.build_goalie_dataset import build
from app.services.ml.train_model import split

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 60


def upload_goalie_model(
    model: Any,
    metadata: dict[str, Any],
    X_hold: pd.DataFrame,
    y_hold: Any,
) -> dict[str, Any]:
    """Gated: status is first_upload / uploaded / rejected_by_champion."""
    return upload_gated_model(S3_PREFIX, MODEL_KEY, model, metadata, X_hold, y_hold)


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
) -> dict[str, Any]:
    features_df, target = build(season_start, season_end)
    if features_df.empty or len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
        }

    model, metadata = train_goalie_model((features_df, target))
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if upload:
        order = feature_names()
        _, X_hold, _, y_hold = split(features_df[order], target, chronological=True)
        out = upload_goalie_model(model, metadata, X_hold, y_hold)
        result["upload"] = out
        if out["status"] == "rejected_by_champion":
            result["status"] = "rejected_by_champion"
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train NHL goalie saves ML model")
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
