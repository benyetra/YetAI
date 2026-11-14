"""Upload trained WNBA prop models — thin wrapper over shared ML package."""

from __future__ import annotations

from typing import Any

import boto3
import xgboost as xgb

from app.services.etl.wnba.ml_training.config import WNBA_ML_CONFIG
from app.services.ml import upload_to_s3 as _shared

S3_BUCKET = _shared.S3_BUCKET
S3_PREFIX = WNBA_ML_CONFIG.s3_prefix


def upload(stat_col: str, model: xgb.XGBRegressor, metadata: dict[str, Any]) -> dict:
    return _shared.upload(WNBA_ML_CONFIG, stat_col, model, metadata, boto3_module=boto3)


def upload_spread_model(model: xgb.XGBRegressor, metadata: dict[str, Any]) -> dict:
    return _shared.upload_spread_model(
        WNBA_ML_CONFIG, model, metadata, boto3_module=boto3
    )


def upload_gated(stat_col: str, model, metadata: dict[str, Any], **kw) -> dict:
    """Champion-gated upload; ``stat_col`` is a prop stat or "spread"."""
    return _shared.upload_gated(WNBA_ML_CONFIG, stat_col, model, metadata, **kw)


def live_scorer(stat_col: str, X_hold, y_hold, **kw):
    return _shared.score_live_mae(WNBA_ML_CONFIG, stat_col, X_hold, y_hold, **kw)
