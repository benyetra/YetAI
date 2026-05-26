from __future__ import annotations

import calendar
import logging
import time
from datetime import date

import pandas as pd

from app.services.etl.mlb.statcast_ingest.normalize import prune_statcast_columns
from app.services.etl.mlb.statcast_ingest.s3_paths import (
    partition_exists,
    partition_uri,
    read_manifest,
    write_manifest,
)

logger = logging.getLogger(__name__)


def _fetch_statcast(start: str, end: str, retries: int = 3) -> pd.DataFrame:
    from pybaseball import statcast

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            df = statcast(start, end)
            return df if df is not None else pd.DataFrame()
        except Exception as exc:
            last_err = exc
            wait = 2**attempt
            logger.warning(
                "statcast %s..%s attempt %s failed: %s", start, end, attempt + 1, exc
            )
            time.sleep(wait)
    raise RuntimeError(f"statcast failed for {start}..{end}") from last_err


def _write_parquet(df: pd.DataFrame, uri: str) -> None:
    if uri.startswith("s3://"):
        import boto3
        from io import BytesIO

        bucket = uri.split("/")[2]
        key = "/".join(uri.split("/")[3:])
        buf = BytesIO()
        df.to_parquet(buf, index=False)
        buf.seek(0)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        return
    path = uri if uri.startswith("/") else uri
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


def backfill_month(season: int, month: int, force: bool = False) -> str | None:
    """Fetch Statcast for one calendar month and write idempotent parquet partition."""
    uri = partition_uri(season, month)
    if partition_exists(uri) and not force:
        logger.info("partition exists, skipping: %s", uri)
        return uri

    last_day = calendar.monthrange(season, month)[1]
    start = f"{season}-{month:02d}-01"
    end = f"{season}-{month:02d}-{last_day:02d}"

    raw = _fetch_statcast(start, end)
    if raw.empty:
        logger.warning("no statcast rows for %s", uri)
        return None

    df = prune_statcast_columns(raw)
    _write_parquet(df, uri)

    manifest = read_manifest(season)
    manifest.append(uri)
    write_manifest(season, manifest)
    logger.info("wrote %s rows → %s", len(df), uri)
    return uri
