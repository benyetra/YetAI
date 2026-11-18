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


def cache_key(
    s3_prefix: str, stat_col: str, start: date, end: date, version: int = 1
) -> str:
    """S3 key for a built dataset; `version` is the feature definition's."""
    base = f"{s3_prefix.rsplit('/', 1)[0]}/ml_datasets/{stat_col}_{start}_{end}"
    return f"{base}.pkl" if version == 1 else f"{base}_v{version}.pkl"


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
    obj = pd.read_pickle(io.BytesIO(body))  # nosec B301 - our own private bucket
    # New entries carry attrs (the row keys the promote gate needs) next to the frame,
    # so they survive whatever a pandas version does with attrs on pickle.
    frame = obj["frame"] if isinstance(obj, dict) else obj
    if isinstance(obj, dict):
        frame.attrs.update(obj.get("attrs") or {})
    target = frame.pop("__target__")
    logger.info("dataset cache hit: %s (%d rows)", key, len(frame))
    return frame, target.rename(None)


def save(key: str, features_df: pd.DataFrame, target: pd.Series) -> None:
    import boto3

    buf = io.BytesIO()
    frame = features_df.assign(__target__=target.to_numpy())
    pd.to_pickle({"frame": frame, "attrs": dict(features_df.attrs)}, buf)
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    logger.info("dataset cache saved: %s (%d rows)", key, len(features_df))
