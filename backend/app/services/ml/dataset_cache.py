"""Cache built training datasets in S3 so experiments don't re-query the DB.

Building a prop dataset is hours of per-row queries; fitting models on it is
minutes. Rows keep their date order, so a cached frame splits chronologically
exactly like a fresh build."""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

BUCKET = "yetibets"


def cache_key(s3_prefix: str, stat_col: str, start: date, end: date) -> str:
    return f"{s3_prefix.rsplit('/', 1)[0]}/ml_datasets/{stat_col}_{start}_{end}.pkl"


def load(key: str):
    """(features_df, target) from the cache, or None when absent."""
    import boto3
    from botocore.exceptions import ClientError

    try:
        body = boto3.client("s3").get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    frame = pd.read_pickle(io.BytesIO(body))  # nosec B301 - our own private bucket
    target = frame.pop("__target__")
    logger.info("dataset cache hit: %s (%d rows)", key, len(frame))
    return frame, target.rename(None)


def save(key: str, features_df: pd.DataFrame, target: pd.Series) -> None:
    import boto3

    buf = io.BytesIO()
    features_df.assign(__target__=target.to_numpy()).to_pickle(buf)
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    logger.info("dataset cache saved: %s (%d rows)", key, len(features_df))
