"""XGBoost stat-projection model loader + predictor (S3-backed), multi-stat.

Port of the YetiBets/scripts/nba/ml_models/predict.py ML path, generalized
across stat types. Each trained `xgb_<stat>.pkl` artifact lives in
s3://yetibets/nba/ml_models/ alongside its `xgb_<stat>_metadata.json`. Each
stat is an `S3Object` pair (model + metadata) held in memory and re-checked
against S3 at most once per `ML_MODEL_REFRESH_SECONDS`, so a weekly retrain
reaches running workers without a restart.

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
import pickle  # nosec B403 - model artifacts loaded from our own private S3 bucket
import threading
from typing import Optional

import numpy as np
import pandas as pd

from app.services.ml.model_store import S3Object

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

# Per-stat (model, metadata) S3Objects. Created lazily by _objects(stat).
_OBJECTS: dict[str, tuple[S3Object, S3Object]] = {}
_load_lock = threading.Lock()


def _s3_keys(stat: str) -> tuple[str, str]:
    return (
        f"nba/ml_models/xgb_{stat}.pkl",
        f"nba/ml_models/xgb_{stat}_metadata.json",
    )


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


def _load_model(body: bytes):
    # nosec B301 - artifact is fetched from our own private S3 bucket
    return _fix_model_gpu_id(pickle.loads(body))  # nosec B301


def _objects(stat: str) -> tuple[S3Object, S3Object]:
    if stat not in SUPPORTED_STATS:
        raise ValueError(f"Unsupported stat {stat!r}; supported: {SUPPORTED_STATS}")
    with _load_lock:
        if stat not in _OBJECTS:
            model_key, meta_key = _s3_keys(stat)
            _OBJECTS[stat] = (
                S3Object(model_key, _load_model, bucket=S3_BUCKET),
                S3Object(meta_key, json.loads, bucket=S3_BUCKET),
            )
        return _OBJECTS[stat]


def _ensure_loaded(stat: str) -> tuple[object, dict]:
    """Current (model, metadata) for `stat`; refreshes from S3 on the shared
    interval and keeps the last good pair if S3 fails."""
    model_obj, meta_obj = _objects(stat)
    model, metadata = model_obj.get(), meta_obj.get()
    if model is None or metadata is None:
        raise RuntimeError(f"NBA {stat} model unavailable from S3")
    return model, metadata


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
    return _feature_order(_ensure_loaded(target)[1])


def get_metadata(stat: Optional[str] = None) -> dict:
    """Expose the full metadata dict (for test_mae, model_version, etc.)."""
    target = stat or "points"
    return dict(_ensure_loaded(target)[1])


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
    """Manifest version (written by the gated upload), else metadata JSON's."""
    _, meta = _ensure_loaded(stat)
    manifest_version = _objects(stat)[0].version
    if manifest_version:
        return manifest_version
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
    model, metadata = _ensure_loaded(stat)

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
