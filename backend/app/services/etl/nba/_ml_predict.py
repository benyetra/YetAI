"""XGBoost points-model loader + predictor (S3-backed).

Port of the points-only slice of YetiBets/scripts/nba/ml_models/predict.py.
The trained `xgb_points.pkl` artifact lives in s3://yetibets/nba/ml_models/
along with its `xgb_points_metadata.json`. On first use we download both into
/tmp and cache the loaded model + metadata in module-level globals so
subsequent calls in the same worker process are zero-IO.

Exposed callable: `predict_points(features_dict) -> float`. The caller is
responsible for building a dict keyed by the feature names — this module
re-orders the dict to match `metadata['feature_names']`, fills missing keys
with 0, coerces inf/NaN to 0, and runs `model.predict` once.
"""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - model artifact loaded from our own private S3 bucket
import tempfile
import threading
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_MODEL_KEY = "nba/ml_models/xgb_points.pkl"
S3_METADATA_KEY = "nba/ml_models/xgb_points_metadata.json"

_TMP_DIR = tempfile.gettempdir()
LOCAL_MODEL_PATH = os.path.join(_TMP_DIR, "xgb_points.pkl")
LOCAL_METADATA_PATH = os.path.join(_TMP_DIR, "xgb_points_metadata.json")

_model = None
_metadata: Optional[dict] = None
_load_lock = threading.Lock()


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


def _ensure_loaded() -> None:
    """Idempotently populate the module-level model + metadata. Re-uses the
    /tmp cache across worker invocations; only hits S3 on cold start."""
    global _model, _metadata
    if _model is not None and _metadata is not None:
        return
    with _load_lock:
        if _model is not None and _metadata is not None:
            return

        if not os.path.exists(LOCAL_MODEL_PATH):
            _download_from_s3(S3_BUCKET, S3_MODEL_KEY, LOCAL_MODEL_PATH)
        if not os.path.exists(LOCAL_METADATA_PATH):
            _download_from_s3(S3_BUCKET, S3_METADATA_KEY, LOCAL_METADATA_PATH)

        with open(LOCAL_MODEL_PATH, "rb") as f:
            # nosec B301 - artifact is fetched from our own private S3 bucket
            model = pickle.load(f)  # nosec B301
        _model = _fix_model_gpu_id(model)

        with open(LOCAL_METADATA_PATH, "r") as f:
            _metadata = json.load(f)

        logger.info(
            "Loaded XGBoost points model (n_features=%s)",
            _metadata.get("n_features"),
        )


def get_feature_names() -> list[str]:
    """Return the canonical 44-feature ordering the model was trained on."""
    _ensure_loaded()
    assert _metadata is not None
    return list(_metadata["feature_names"])


def get_metadata() -> dict:
    """Expose the full metadata dict (for test_mae, etc.)."""
    _ensure_loaded()
    assert _metadata is not None
    return _metadata


def predict_points(features: dict) -> float:
    """Run the loaded XGBoost model against a single feature dict.

    Missing keys default to 0 (matches the training pipeline's behavior in
    YetiBets/scripts/nba/ml_models/predict.py — features not produced by the
    extractor are filled with zeros before model.predict).
    """
    _ensure_loaded()
    assert _model is not None and _metadata is not None

    feature_names = _metadata["feature_names"]
    row = {name: features.get(name, 0) for name in feature_names}
    X = pd.DataFrame([row], columns=feature_names)

    # Coerce object dtypes to numeric, then nuke inf/NaN — same defensive
    # cleanup the original predictor did.
    for col in X.columns:
        if X[col].dtype == "object":
            X[col] = pd.to_numeric(X[col], errors="coerce")
    X = X.replace([np.inf, -np.inf], 0).fillna(0)

    prediction = float(_model.predict(X)[0])
    return prediction
