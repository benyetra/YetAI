"""S3-backed XGBoost spread margin predictor for WNBA."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our own private bucket
import tempfile
import threading
from pathlib import Path

import boto3
import numpy as np

from app.services.etl.wnba.ml_training.config import SPREAD_MAE_GATE
from app.services.etl.wnba.ml_training.validate_spread_model import validate_holdout

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "wnba/ml_models"
MODEL_KEY = "xgb_spread"
MIN_TRAINING_ROWS = 40

_MODEL: object | None = None
_METADATA: dict | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


def _download_artifact(s3_key: str, local_path: Path) -> None:
    s3 = boto3.client("s3")
    s3.download_file(S3_BUCKET, s3_key, str(local_path))


def _ensure_loaded() -> bool:
    global _MODEL, _METADATA, _LOAD_FAILED
    if _MODEL is not None and _METADATA is not None:
        return True
    if _LOAD_FAILED:
        return False
    with _LOCK:
        if _MODEL is not None and _METADATA is not None:
            return True
        if _LOAD_FAILED:
            return False
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                model_local = tmp / f"{MODEL_KEY}.pkl"
                meta_local = tmp / f"{MODEL_KEY}_metadata.json"
                _download_artifact(f"{S3_PREFIX}/{MODEL_KEY}.pkl", model_local)
                _download_artifact(f"{S3_PREFIX}/{MODEL_KEY}_metadata.json", meta_local)
                with model_local.open("rb") as f:
                    _MODEL = pickle.load(f)  # nosec B301
                _METADATA = json.loads(meta_local.read_text())
            return True
        except Exception as exc:
            logger.info("WNBA spread ML model unavailable, using Elo+pace: %s", exc)
            _LOAD_FAILED = True
            return False


def get_metadata() -> dict | None:
    if not _ensure_loaded() or _METADATA is None:
        return None
    return dict(_METADATA)


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
    if not _ensure_loaded():
        return False
    if passes_quality_gate(_METADATA):
        return True
    logger.info(
        "WNBA spread ML loaded but failed quality gate; using Elo+pace "
        "(test_mae=%s test_brier=%s). Set WNBA_SPREAD_ML_FORCE=1 to override.",
        (_METADATA or {}).get("test_mae"),
        (_METADATA or {}).get("test_brier"),
    )
    return False


def get_feature_names() -> list[str]:
    if not _ensure_loaded() or _METADATA is None:
        return []
    return list(_METADATA["features"])


def predict_margin(features_dict: dict[str, float]) -> float | None:
    """Return projected home margin, or None if model not loaded / gated out."""
    if not model_available() or _MODEL is None or _METADATA is None:
        return None
    feature_order = _METADATA["features"]
    vec = np.array([[float(features_dict.get(f, 0.0)) for f in feature_order]])
    return float(_MODEL.predict(vec)[0])
