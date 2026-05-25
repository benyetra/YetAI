"""XGBoost stat-projection model loader + predictor (S3-backed), multi-stat.

Port of the YetiBets/scripts/nba/ml_models/predict.py ML path, generalized
across stat types. Each trained `xgb_<stat>.pkl` artifact lives in
s3://yetibets/nba/ml_models/ alongside its `xgb_<stat>_metadata.json`. On first
use per stat we download both into a temp dir and cache the loaded model +
metadata in module-level per-stat dicts so subsequent calls in the same worker
process are zero-IO.

Exposed callables:
  * `predict(stat, features_dict) -> float`
  * `get_feature_names(stat) -> list[str]`
  * `get_metadata(stat) -> dict`

Backward-compat wrappers (keyed on "points"):
  * `predict_points(features_dict) -> float`
  * (No-arg) `get_feature_names()` still returns the points model's feature
    names if called with no `stat` arg, to preserve the existing public API
    used by `generate_points_predictions.py`.
"""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - model artifacts loaded from our own private S3 bucket
import tempfile
import threading
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"

# Stats this module knows how to load. Adding a new stat is just adding it
# here; both the .pkl and the matching _metadata.json must exist under
# s3://yetibets/nba/ml_models/.
SUPPORTED_STATS: tuple[str, ...] = (
    "points",
    "rebounds",
    "assists",
    "three_pt_made",
    "free_throws_made",
    "steals",
    "blocks",
)

_TMP_DIR = tempfile.gettempdir()

# Per-stat model + metadata caches. Populated lazily by _ensure_loaded(stat).
_models: dict[str, object] = {}
_metadatas: dict[str, dict] = {}
_load_lock = threading.Lock()


def _s3_keys(stat: str) -> tuple[str, str]:
    return (
        f"nba/ml_models/xgb_{stat}.pkl",
        f"nba/ml_models/xgb_{stat}_metadata.json",
    )


def _local_paths(stat: str) -> tuple[str, str]:
    return (
        os.path.join(_TMP_DIR, f"xgb_{stat}.pkl"),
        os.path.join(_TMP_DIR, f"xgb_{stat}_metadata.json"),
    )


def _download_from_s3(bucket: str, key: str, local_path: str) -> None:
    """Pull a single object from S3 onto local disk. Uses boto3's default
    credential chain (env vars / IAM role)."""
    import boto3  # imported lazily so the module imports cheap when unused

    s3 = boto3.client("s3")
    logger.info("Downloading s3://%s/%s -> %s", bucket, key, local_path)
    s3.download_file(bucket, key, local_path)


def _fix_model_gpu_id(model):
    """XGBoost models trained on older versions sometimes carry a `gpu_id`
    attribute that newer xgboost rejects. Clearing it (and forcing device=cpu)
    keeps load+predict working on the celery worker which has no GPU.
    Lifted verbatim from YetiBets/scripts/nba/ml_models/predict.py."""
    if hasattr(model, "gpu_id"):
        try:
            model.gpu_id = None
        except Exception:
            pass
    if hasattr(model, "device"):
        try:
            model.device = "cpu"
        except Exception:
            pass
    return model


def _ensure_loaded(stat: str) -> None:
    """Idempotently populate the per-stat model + metadata. Re-uses the
    on-disk cache across worker invocations; only hits S3 on cold start."""
    if stat not in SUPPORTED_STATS:
        raise ValueError(f"Unsupported stat {stat!r}; supported: {SUPPORTED_STATS}")
    if stat in _models and stat in _metadatas:
        return
    with _load_lock:
        if stat in _models and stat in _metadatas:
            return

        model_key, meta_key = _s3_keys(stat)
        local_model, local_meta = _local_paths(stat)

        if not os.path.exists(local_model):
            _download_from_s3(S3_BUCKET, model_key, local_model)
        if not os.path.exists(local_meta):
            _download_from_s3(S3_BUCKET, meta_key, local_meta)

        with open(local_model, "rb") as f:
            # nosec B301 - artifact is fetched from our own private S3 bucket
            model = pickle.load(f)  # nosec B301
        _models[stat] = _fix_model_gpu_id(model)

        with open(local_meta, "r") as f:
            _metadatas[stat] = json.load(f)

        logger.info(
            "Loaded XGBoost %s model (n_features=%s)",
            stat,
            _metadatas[stat].get("n_features"),
        )


def _feature_order(metadata: dict) -> list[str]:
    """Training artifacts use ``features``; legacy YetiBets JSON used ``feature_names``."""
    names = metadata.get("feature_names") or metadata.get("features")
    if not names:
        raise KeyError("metadata missing feature_names/features")
    return list(names)


def get_feature_names(stat: Optional[str] = None) -> list[str]:
    """Return the canonical feature ordering the model was trained on.

    `stat=None` is a backward-compat shim that returns the points-model
    feature ordering (preserves the existing import in
    generate_points_predictions.py).
    """
    target = stat or "points"
    _ensure_loaded(target)
    return _feature_order(_metadatas[target])


def get_metadata(stat: Optional[str] = None) -> dict:
    """Expose the full metadata dict (for test_mae, model_version, etc.)."""
    target = stat or "points"
    _ensure_loaded(target)
    return dict(_metadatas[target])


def get_holdout_mae(stat: str) -> float | None:
    """Holdout MAE from training metadata (``holdout_mae`` or ``test_mae``)."""
    meta = get_metadata(stat)
    for key in ("holdout_mae", "test_mae", "mae"):
        value = meta.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def get_model_version(stat: str) -> str | None:
    """Promotion tag from metadata JSON, if present."""
    meta = get_metadata(stat)
    version = meta.get("model_version")
    if version is not None and str(version).strip():
        return str(version).strip()
    return None


def predict(stat: str, features: dict) -> float:
    """Run the loaded XGBoost model for `stat` against a single feature dict.

    Missing keys default to 0 (matches the training pipeline's behavior in
    YetiBets/scripts/nba/ml_models/predict.py — features not produced by the
    extractor are filled with zeros before model.predict).
    """
    _ensure_loaded(stat)
    model = _models[stat]
    metadata = _metadatas[stat]

    feature_names = _feature_order(metadata)
    row = {name: features.get(name, 0) for name in feature_names}
    X = pd.DataFrame([row], columns=feature_names)

    # Coerce object dtypes to numeric, then nuke inf/NaN — same defensive
    # cleanup the original predictor did.
    for col in X.columns:
        if X[col].dtype == "object":
            X[col] = pd.to_numeric(X[col], errors="coerce")
    X = X.replace([np.inf, -np.inf], 0).fillna(0)

    prediction = float(model.predict(X)[0])
    return prediction


def predict_points(features: dict) -> float:
    """Backward-compat wrapper around `predict("points", ...)`. Preserves the
    existing import in generate_points_predictions.py."""
    return predict("points", features)
