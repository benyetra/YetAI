"""S3-backed XGBoost spread margin predictor for NBA."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts from our own private bucket
import threading

import numpy as np

from app.services.ml.model_store import S3Object

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "nba/ml_models"
MODEL_KEY = "xgb_spread"
MIN_TRAINING_ROWS = 40

# (model, metadata) S3Objects, built on first use. They re-check S3 on the
# shared refresh interval and keep the last good copy on any failure.
_OBJECTS: tuple[S3Object, S3Object] | None = None
_warned_for: dict | None = None  # metadata we last logged as ignored
_LOCK = threading.Lock()


def beats_baseline(metadata: dict) -> bool:
    """Only models whose metadata shows a win over Elo on games after their
    training window may replace it. Older uploads carry no baseline, and ones
    validated on a random split flatter the model, so both are ignored."""
    try:
        if metadata.get("split") != "chronological":
            return False
        return float(metadata["test_mae"]) < float(metadata["baseline_test_mae"])
    except (KeyError, TypeError, ValueError):
        return False


def _objects() -> tuple[S3Object, S3Object]:
    global _OBJECTS
    with _LOCK:
        if _OBJECTS is None:
            _OBJECTS = (
                S3Object(
                    f"{S3_PREFIX}/{MODEL_KEY}.pkl",
                    lambda b: pickle.loads(b),  # nosec B301
                    bucket=S3_BUCKET,
                ),
                S3Object(
                    f"{S3_PREFIX}/{MODEL_KEY}_metadata.json",
                    json.loads,
                    bucket=S3_BUCKET,
                ),
            )
        return _OBJECTS


def _loaded() -> tuple[object, dict] | None:
    """(model, metadata) when a model is loaded and beats Elo, else None.

    Not sticky: a model that does not qualify is ignored only until a newer
    upload replaces it (picked up at the next refresh)."""
    global _warned_for
    model_obj, meta_obj = _objects()
    model, metadata = model_obj.get(), meta_obj.get()
    if model is None or metadata is None:
        return None
    if not beats_baseline(metadata):
        if _warned_for is not metadata:
            _warned_for = metadata
            logger.warning(
                "NBA spread ML model ignored (no Elo holdout win): "
                "test_mae=%s baseline=%s",
                metadata.get("test_mae"),
                metadata.get("baseline_test_mae"),
            )
        return None
    return model, metadata


def model_available() -> bool:
    return _loaded() is not None


def get_model_version() -> str | None:
    """Manifest version from the gated upload, else the metadata's tag."""
    loaded = _loaded()
    if loaded is None:
        return None
    version = _objects()[0].version
    if version:
        return version
    tag = str(loaded[1].get("model_version") or "").strip()
    return tag or None


def get_feature_names() -> list[str]:
    loaded = _loaded()
    return list(loaded[1]["features"]) if loaded else []


def predict_margin(features_dict: dict[str, float]) -> float | None:
    """Return projected home margin, or None if model not loaded."""
    loaded = _loaded()
    if loaded is None:
        return None
    model, metadata = loaded
    vec = np.array(
        [
            [
                np.nan if features_dict.get(f) is None else float(features_dict[f])
                for f in metadata["features"]
            ]
        ]
    )
    return float(model.predict(vec)[0])
