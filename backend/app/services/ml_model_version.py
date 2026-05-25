"""Resolve short model_version tags for prediction table writes.

Tags are capped at 20 characters to match ``predictions_models`` columns.
Sources (in order): explicit metadata JSON on S3, training run id, artifact
mtime, then stable heuristic defaults.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

MAX_MODEL_VERSION_LEN = 20
_S3_BUCKET = "yetibets"

# Optional sidecar metadata (WNBA-style); not required for inference today.
MLB_STRIKEOUT_METADATA_S3_KEY = "mlb/strikeout_model_metadata.json"
MLB_GAME_METADATA_S3_KEY = "mlb/game_model_metadata.json"

_VERSION_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def normalize_model_version(
    value: Any,
    *,
    max_len: int = MAX_MODEL_VERSION_LEN,
    fallback: str = "unknown",
) -> str:
    """Coerce *value* into a DB-safe model_version string."""
    if value is None:
        raw = fallback
    else:
        raw = str(value).strip()
    if not raw:
        raw = fallback
    cleaned = _VERSION_SAFE.sub("-", raw).strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len]


def model_version_from_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    prefix: str = "xgb",
    fallback: str | None = None,
) -> str:
    """Build a version tag from training/upload metadata JSON."""
    if not metadata:
        return normalize_model_version(fallback or f"{prefix}-v1")

    for key in ("model_version", "training_run_id", "train_date", "trained_at"):
        if metadata.get(key):
            return normalize_model_version(metadata[key])

    for key in ("test_mae", "holdout_mae", "mae"):
        mae = metadata.get(key)
        if mae is not None:
            try:
                return normalize_model_version(f"{prefix}-mae{float(mae):.1f}")
            except (TypeError, ValueError):
                pass

    return normalize_model_version(fallback or f"{prefix}-v1")


def fetch_s3_metadata_json(
    s3_key: str,
    *,
    bucket: str = _S3_BUCKET,
    allow_network: bool | None = None,
) -> dict[str, Any] | None:
    """Load optional ``*_metadata.json`` from S3 (no-op when network disabled)."""
    if allow_network is None:
        allow_network = os.getenv("ML_MODEL_VERSION_ALLOW_S3", "1") == "1"
    if not allow_network:
        return None
    try:
        import boto3
    except ImportError:
        return None
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=s3_key)
        data = json.loads(obj["Body"].read())
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("S3 metadata missing for %s: %s", s3_key, exc)
        return None


def s3_object_version_date(
    s3_key: str,
    *,
    bucket: str = _S3_BUCKET,
    local_fallback: Path | None = None,
    allow_network: bool | None = None,
) -> str | None:
    """Artifact date suffix (YYYYMMDD) from S3 LastModified or local mtime."""
    if allow_network is None:
        allow_network = os.getenv("ML_MODEL_VERSION_ALLOW_S3", "1") == "1"
    if allow_network:
        try:
            import boto3

            s3 = boto3.client("s3")
            head = s3.head_object(Bucket=bucket, Key=s3_key)
            lm = head.get("LastModified")
            if isinstance(lm, datetime):
                return lm.astimezone(timezone.utc).strftime("%Y%m%d")
        except Exception:
            pass
    if local_fallback and local_fallback.is_file():
        mtime = datetime.fromtimestamp(local_fallback.stat().st_mtime, tz=timezone.utc)
        return mtime.strftime("%Y%m%d")
    return None


def resolve_mlb_strikeout_model_version(
    *,
    classifier_loaded: bool = True,
    allow_network: bool | None = None,
) -> str:
    """Version tag for ``pred_strikeout_projections`` writes."""
    override = os.getenv("MLB_STRIKEOUT_MODEL_VERSION")
    if override:
        return normalize_model_version(override)

    meta = fetch_s3_metadata_json(
        MLB_STRIKEOUT_METADATA_S3_KEY, allow_network=allow_network
    )
    if meta:
        return model_version_from_metadata(meta, prefix="gb", fallback="gb-v1")

    from app.services.etl.mlb.classification_model import MODEL_LOCAL_PATH, S3_KEY

    if classifier_loaded:
        date_suffix = s3_object_version_date(
            S3_KEY,
            local_fallback=Path(MODEL_LOCAL_PATH),
            allow_network=allow_network,
        )
        if date_suffix:
            return normalize_model_version(f"gb-{date_suffix}")
        return normalize_model_version("gb-cal-v1")

    return normalize_model_version("heuristic-v1")


def resolve_mlb_game_projection_model_version(
    *,
    win_model: Any = None,
    allow_network: bool | None = None,
) -> str:
    """Version tag for ``pred_game_projections`` writes."""
    override = os.getenv("MLB_GAME_MODEL_VERSION")
    if override:
        return normalize_model_version(override)

    meta = fetch_s3_metadata_json(MLB_GAME_METADATA_S3_KEY, allow_network=allow_network)
    if meta:
        return model_version_from_metadata(
            meta, prefix="ensemble", fallback="ensemble-v1"
        )

    if win_model is None:
        from app.services.etl.mlb.game_model import load_model

        win_model = load_model("win")

    use_ml = win_model is not None
    if not use_ml:
        return normalize_model_version("heuristic-v1")

    if isinstance(win_model, dict) and "weights" in win_model:
        cols = win_model.get("feature_cols") or []
        n = len(cols) if cols else 0
        if n:
            return normalize_model_version(f"ens-{n}f")
        from app.services.etl.mlb.game_model import (
            WIN_MODEL_LOCAL,
            WIN_MODEL_S3_KEY,
            ensemble_feature_cols,
        )

        n = len(ensemble_feature_cols(win_model))
        tag = f"ens-{n}f" if n else "ensemble-v1"
        date_suffix = s3_object_version_date(
            WIN_MODEL_S3_KEY,
            local_fallback=Path(WIN_MODEL_LOCAL),
            allow_network=allow_network,
        )
        if date_suffix and len(f"ens-{date_suffix}") <= MAX_MODEL_VERSION_LEN:
            return normalize_model_version(f"ens-{date_suffix}")
        return normalize_model_version(tag)

    from app.services.etl.mlb.game_model import WIN_MODEL_LOCAL, WIN_MODEL_S3_KEY

    date_suffix = s3_object_version_date(
        WIN_MODEL_S3_KEY,
        local_fallback=Path(WIN_MODEL_LOCAL),
        allow_network=allow_network,
    )
    if date_suffix:
        return normalize_model_version(f"xgb-{date_suffix}")
    return normalize_model_version("xgb-v1")


def resolve_nba_prop_model_version(
    stat: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allow_network: bool | None = None,
) -> str:
    """Version tag for NBA ``pred_*_projections`` writes (points/rebounds/assists)."""
    override = os.getenv("NBA_PROP_MODEL_VERSION") or os.getenv(
        f"NBA_{stat.upper()}_MODEL_VERSION"
    )
    if override:
        return normalize_model_version(override)

    if metadata is None:
        if allow_network is False:
            return normalize_model_version(f"xgb-{stat}-v1")
        from app.services.etl.nba._ml_predict import get_metadata

        metadata = get_metadata(stat)

    if metadata:
        return model_version_from_metadata(
            metadata, prefix="xgb", fallback=f"xgb-{stat}-v1"
        )

    date_suffix = s3_object_version_date(
        f"nba/ml_models/xgb_{stat}.pkl",
        local_fallback=Path(tempfile.gettempdir()) / f"xgb_{stat}.pkl",
        allow_network=allow_network,
    )
    if date_suffix:
        return normalize_model_version(f"xgb-{date_suffix}")
    return normalize_model_version(f"xgb-{stat}-v1")


def attach_model_version(row: Any, version: str) -> None:
    """Set ``model_version`` on an ORM row when the column exists."""
    if hasattr(row, "model_version"):
        row.model_version = normalize_model_version(version)
