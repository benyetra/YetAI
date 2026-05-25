"""Train NFL QB passing yards regressor and optionally upload to S3."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import boto3

from app.services.etl.nfl.ml_training.build_qb_dataset import build
from app.services.etl.nfl.qb_passing_yards_ml import (
    MODEL_KEY,
    S3_BUCKET,
    S3_PREFIX,
    train_qb_yards_model,
)

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 40
S3_OBJECT_KEY = f"{S3_PREFIX}/{MODEL_KEY}.pkl"
S3_META_KEY = f"{S3_PREFIX}/{MODEL_KEY}_metadata.json"


def upload_qb_model(
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

    model, metadata = train_qb_yards_model((features_df, target))
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if upload:
        keys = upload_qb_model(model, metadata)
        result["s3_keys"] = keys
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Train NFL QB passing yards ML")
    parser.add_argument("--season-start", type=str, required=True)
    parser.add_argument("--season-end", type=str, required=True)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    out = run(
        season_start=date.fromisoformat(args.season_start),
        season_end=date.fromisoformat(args.season_end),
        upload=args.upload,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
