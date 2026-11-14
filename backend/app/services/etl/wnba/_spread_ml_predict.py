"""S3-backed XGBoost spread margin predictor for WNBA."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our own private bucket
import threading

import numpy as np

from app.services.etl.wnba.ml_training.config import SPREAD_MAE_GATE
from app.services.etl.wnba.ml_training.validate_spread_model import validate_holdout
from app.services.ml.model_store import S3Object

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "wnba/ml_models"
MODEL_KEY = "xgb_spread"
MIN_TRAINING_ROWS = 40

# (model, metadata) S3Objects, built on first use. They re-check S3 on the
# shared refresh interval and keep the last good copy on any failure.
_OBJECTS: tuple[S3Object, S3Object] | None = None
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


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
    """(model, metadata) once a model has loaded, else None. Not sticky: a
    failed load is retried at the next refresh."""
    model_obj, meta_obj = _objects()
    model, metadata = model_obj.get(), meta_obj.get()
    if model is None or metadata is None:
        return None
    return model, metadata


def get_metadata() -> dict | None:
    loaded = _loaded()
    return dict(loaded[1]) if loaded else None


def passes_quality_gate(metadata: dict | None = None) -> bool:
    """
    True when metadata clears MAE/Brier gates (or ops force-enable).

    Legacy S3 artifacts without ``validation`` / ``test_brier`` fall back to
    ``test_mae`` alone; missing metrics refuse ML so Elo+pace is used.
    """
    if os.getenv("WNBA_SPREAD_ML_FORCE", "").strip().lower() in _TRUTHY:
        return True
    meta = metadata if metadata is not None else get_metadata()
    if not meta:
        return False
    validation = meta.get("validation")
    if isinstance(validation, dict) and "passes_gate" in validation:
        return bool(validation["passes_gate"])
    # Legacy: MAE-only check when Brier was never recorded.
    if meta.get("test_brier") is None and meta.get("test_mae") is not None:
        return float(meta["test_mae"]) <= SPREAD_MAE_GATE
    return bool(validate_holdout(meta)["passes_gate"])


def model_available() -> bool:
    """True when S3 model loads AND clears the quality gate (else Elo fallback)."""
    loaded = _loaded()
    if loaded is None:
        return False
    metadata = loaded[1]
    if passes_quality_gate(metadata):
        return True
    logger.info(
        "WNBA spread ML loaded but failed quality gate; using Elo+pace "
        "(test_mae=%s test_brier=%s). Set WNBA_SPREAD_ML_FORCE=1 to override.",
        metadata.get("test_mae"),
        metadata.get("test_brier"),
    )
    return False


def get_feature_names() -> list[str]:
    loaded = _loaded()
    return list(loaded[1]["features"]) if loaded else []


def predict_margin(features_dict: dict[str, float]) -> float | None:
    """Return projected home margin, or None if model not loaded / gated out."""
    if not model_available():
        return None
    model, metadata = _loaded()  # type: ignore[misc]
    vec = np.array([[float(features_dict.get(f, 0.0)) for f in metadata["features"]]])
    return float(model.predict(vec)[0])


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
