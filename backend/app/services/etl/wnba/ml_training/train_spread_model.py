"""Train WNBA spread margin XGBoost and optionally upload to S3."""

from __future__ import annotations

import logging
from datetime import date

from app.services.etl.wnba._spread_ml_predict import MIN_TRAINING_ROWS
from app.services.etl.wnba.ml_training.build_spread_dataset import build
from app.services.etl.wnba.ml_training.train_model import train
from app.services.etl.wnba.ml_training.upload_to_s3 import upload_spread_model

logger = logging.getLogger(__name__)


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

    model, metadata = train("spread", features_df, target)
    result = {"status": "ok", "metadata": metadata, "rows": len(features_df)}
    if upload:
        keys = upload_spread_model(model, metadata)
        result["s3_keys"] = keys
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train WNBA spread ML model")
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
