"""S3-backed XGBoost loader and predictor for WNBA prop models."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts from our own private bucket
import threading

import numpy as np

from app.services.ml.model_store import S3Object

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "wnba/ml_models"
SUPPORTED_STATS: tuple[str, ...] = ("points", "assists", "rebounds", "three_pt_made")

# Per-stat (model, metadata) S3Objects, built on first use. They re-check S3 on
# the shared refresh interval and keep the last good copy on any failure.
_OBJECTS: dict[str, tuple[S3Object, S3Object]] = {}
_LOCK = threading.Lock()


def _ensure_loaded(stat: str) -> tuple[object, dict]:
    if stat not in SUPPORTED_STATS:
        raise ValueError(f"unsupported stat: {stat}")
    with _LOCK:
        if stat not in _OBJECTS:
            _OBJECTS[stat] = (
                S3Object(
                    f"{S3_PREFIX}/xgb_{stat}.pkl",
                    lambda b: pickle.loads(b),  # nosec B301
                    bucket=S3_BUCKET,
                ),
                S3Object(
                    f"{S3_PREFIX}/xgb_{stat}_metadata.json",
                    json.loads,
                    bucket=S3_BUCKET,
                ),
            )
        model_obj, meta_obj = _OBJECTS[stat]
    model, metadata = model_obj.get(), meta_obj.get()
    if model is None or metadata is None:
        raise RuntimeError(f"WNBA {stat} model unavailable from S3")
    return model, metadata


def get_feature_names(stat: str) -> list[str]:
    return list(_ensure_loaded(stat)[1]["features"])


def get_metadata(stat: str) -> dict:
    """Metadata JSON; ``model_version`` is the gated upload's manifest version when present."""
    meta = dict(_ensure_loaded(stat)[1])
    version = _OBJECTS[stat][0].version
    if version:
        meta["model_version"] = version
    return meta


def predict(stat: str, features_dict: dict[str, float]) -> float:
    """Run inference. Features the model expects but aren't in features_dict are filled with 0.0."""
    model, metadata = _ensure_loaded(stat)
    vec = np.array([[float(features_dict.get(f, 0.0)) for f in metadata["features"]]])
    pred = float(model.predict(vec)[0])
    return max(0.0, pred)  # clamp negative predictions to 0
