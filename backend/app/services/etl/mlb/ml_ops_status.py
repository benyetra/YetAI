"""MLB ML ops status for admin API (prod DB + S3 + local backtest runs)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.etl.mlb.backtest.persistence import list_runs
from app.services.etl.mlb.strikeout_training import (
    get_strikeout_table_counts,
    min_joined_rows,
    should_retrain_strikeout_classifier,
)


def _s3_head(uri: str) -> dict[str, Any] | None:
    if not uri.startswith("s3://"):
        p = Path(uri)
        if not p.is_file():
            return None
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        return {
            "uri": str(p),
            "last_modified": mtime.isoformat(),
            "size_bytes": p.stat().st_size,
        }
    try:
        import boto3

        bucket, key = uri.split("/")[2], "/".join(uri.split("/")[3:])
        obj = boto3.client("s3").head_object(Bucket=bucket, Key=key)
        return {
            "uri": uri,
            "last_modified": obj["LastModified"].astimezone(timezone.utc).isoformat(),
            "size_bytes": obj.get("ContentLength"),
        }
    except Exception:
        return None


def _read_retrain_metrics() -> dict[str, Any] | None:
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "mlb_strikeout_retrain_metrics.json"
    )
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def collect_ml_ops_status() -> dict[str, Any]:
    from app.services.etl.mlb._db import close_session, init_session
    from app.services.etl.mlb.classification_model import S3_BUCKET, S3_KEY

    init_session()
    try:
        return _collect_ml_ops_status_inner(S3_BUCKET, S3_KEY)
    finally:
        close_session()


def _collect_ml_ops_status_inner(s3_bucket: str, s3_key: str) -> dict[str, Any]:
    from app.services.etl.mlb.classification_model import probe_classifier_load

    counts = get_strikeout_table_counts()
    minimum = min_joined_rows()
    ready, retrain_reason = should_retrain_strikeout_classifier(counts)
    strikeout_s3 = os.getenv("MLB_STRIKEOUT_MODEL_S3", f"s3://{s3_bucket}/{s3_key}")
    hr_s3 = os.getenv("MLB_HR_MODEL_S3", "s3://yetibets/mlb/hr_model.pkl")

    runs = list_runs(limit=10)
    last_backtest = runs[0] if runs else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strikeout_training": {
            **counts,
            "min_joined_required": minimum,
            "ready_to_retrain": ready,
            "retrain_reason": retrain_reason,
        },
        "models": {
            "strikeout_classifier": _s3_head(strikeout_s3),
            "hr_model": _s3_head(hr_s3),
        },
        "strikeout_classifier_load": probe_classifier_load(),
        "last_strikeout_retrain": _read_retrain_metrics(),
        "backtest_runs": runs,
        "last_backtest_summary": (
            {
                "id": last_backtest.get("id"),
                "run_date": last_backtest.get("run_date"),
                "model_version": last_backtest.get("model_version"),
                "n_games": last_backtest.get("n_games"),
                "metrics": last_backtest.get("metrics"),
            }
            if last_backtest
            else None
        ),
        "env": {
            "MLB_HR_S3_PREFIX": os.getenv("MLB_HR_S3_PREFIX", "s3://yetibets/mlb/"),
            "MLB_STRIKEOUT_MIN_JOINED_ROWS": minimum,
        },
    }
