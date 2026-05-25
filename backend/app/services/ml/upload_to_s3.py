"""Upload a trained, validated prop model to s3://yetibets/<league>/ml_models/."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
import tempfile
from pathlib import Path
from typing import Any

import boto3
import xgboost as xgb

from app.services.ml.config import LeagueMLConfig

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"


def upload(
    config: LeagueMLConfig,
    stat_col: str,
    model: xgb.XGBRegressor,
    metadata: dict[str, Any],
    *,
    boto3_module: Any | None = None,
) -> dict:
    """Upload xgb_<stat>.pkl + xgb_<stat>_metadata.json. Returns S3 keys written."""
    boto3_mod = boto3_module if boto3_module is not None else boto3
    s3 = boto3_mod.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / f"xgb_{stat_col}.pkl"
        meta_path = Path(tmpdir) / f"xgb_{stat_col}_metadata.json"
        with model_path.open("wb") as f:
            pickle.dump(model, f)
        meta_path.write_text(json.dumps(metadata, indent=2, default=str))

        model_key = f"{config.s3_prefix}/xgb_{stat_col}.pkl"
        meta_key = f"{config.s3_prefix}/xgb_{stat_col}_metadata.json"
        s3.upload_file(str(model_path), S3_BUCKET, model_key)
        s3.upload_file(str(meta_path), S3_BUCKET, meta_key)
        logger.info(
            "uploaded s3://%s/%s and s3://%s/%s",
            S3_BUCKET,
            model_key,
            S3_BUCKET,
            meta_key,
        )
        return {"model_key": model_key, "metadata_key": meta_key}


def upload_spread_model(
    config: LeagueMLConfig,
    model: xgb.XGBRegressor,
    metadata: dict[str, Any],
    *,
    boto3_module: Any | None = None,
) -> dict:
    """Upload spread margin model as xgb_spread.pkl."""
    return upload(config, "spread", model, metadata, boto3_module=boto3_module)
