"""Upload trained NBA prop models — thin wrapper over shared ML package."""

from __future__ import annotations

from typing import Any

import boto3
import xgboost as xgb

from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.ml import upload_to_s3 as _shared

S3_BUCKET = _shared.S3_BUCKET
S3_PREFIX = NBA_ML_CONFIG.s3_prefix


def upload(stat_col: str, model: xgb.XGBRegressor, metadata: dict[str, Any]) -> dict:
    return _shared.upload(NBA_ML_CONFIG, stat_col, model, metadata, boto3_module=boto3)


def upload_spread_model(model: xgb.XGBRegressor, metadata: dict[str, Any]) -> dict:
    return _shared.upload_spread_model(
        NBA_ML_CONFIG, model, metadata, boto3_module=boto3
    )
