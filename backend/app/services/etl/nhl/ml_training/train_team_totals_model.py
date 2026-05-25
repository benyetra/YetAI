"""Train NHL team totals residual GBM and optionally upload to S3."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import boto3

from app.services.etl.nhl.ml_training.build_team_totals_dataset import build
from app.services.etl.nhl.team_totals_ml import (
    MODEL_KEY,
    S3_BUCKET,
    S3_PREFIX,
    train_team_totals_model,
)

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 40
S3_OBJECT_KEY = f"{S3_PREFIX}/{MODEL_KEY}.pkl"
S3_META_KEY = f"{S3_PREFIX}/{MODEL_KEY}_metadata.json"


def upload_team_totals_model(
    model: Any,
    metadata: dict[str, Any],
    *,
    boto3_module: Any | None = None,
) -> dict[str, str]:
    boto3_mod = boto3_module if boto3_module is not None else boto3
    s3 = boto3_mod.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / f"{MODEL_KEY}.pkl"
        meta_path = Path(tmpdir) / f"{MODEL_KEY}_metadata.json"
        with model_path.open("wb") as f:
            pickle.dump(model, f)
        meta_path.write_text(json.dumps(metadata, indent=2, default=str))

        s3.upload_file(str(model_path), S3_BUCKET, S3_OBJECT_KEY)
        s3.upload_file(str(meta_path), S3_BUCKET, S3_META_KEY)
        logger.info(
            "uploaded s3://%s/%s and s3://%s/%s",
            S3_BUCKET,
            S3_OBJECT_KEY,
            S3_BUCKET,
            S3_META_KEY,
        )
        return {"model_key": S3_OBJECT_KEY, "metadata_key": S3_META_KEY}


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

    model, metadata = train_team_totals_model((features_df, target))
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if upload:
        keys = upload_team_totals_model(model, metadata)
        result["s3_keys"] = keys
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train NHL team totals ML model")
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
