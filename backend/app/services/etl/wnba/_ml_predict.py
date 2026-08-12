"""S3-backed XGBoost loader and predictor for WNBA prop models."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts from our own private bucket
import tempfile
import threading
from pathlib import Path

import boto3
import numpy as np

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "wnba/ml_models"
SUPPORTED_STATS: tuple[str, ...] = ("points", "assists", "rebounds", "three_pt_made")

_MODELS: dict[str, object] = {}
_METADATA: dict[str, dict] = {}
_LOCK = threading.Lock()


def _download_artifact(s3_key: str, local_path: Path) -> None:
    """Download s3://yetibets/<s3_key> → local_path. Override-able in tests."""
    s3 = boto3.client("s3")
    s3.download_file(S3_BUCKET, s3_key, str(local_path))


def _ensure_loaded(stat: str) -> None:
    if stat not in SUPPORTED_STATS:
        raise ValueError(f"unsupported stat: {stat}")
    if stat in _MODELS and stat in _METADATA:
        return
    with _LOCK:
        if stat in _MODELS and stat in _METADATA:
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            model_local = tmp / f"xgb_{stat}.pkl"
            meta_local = tmp / f"xgb_{stat}_metadata.json"
            _download_artifact(f"{S3_PREFIX}/xgb_{stat}.pkl", model_local)
            _download_artifact(f"{S3_PREFIX}/xgb_{stat}_metadata.json", meta_local)
            with model_local.open("rb") as f:
                _MODELS[stat] = pickle.load(f)  # nosec B301
            _METADATA[stat] = json.loads(meta_local.read_text())


def get_feature_names(stat: str) -> list[str]:
    if stat not in _METADATA:
        _ensure_loaded(stat)
    return list(_METADATA[stat]["features"])


def get_metadata(stat: str) -> dict:
    if stat not in _METADATA:
        _ensure_loaded(stat)
    return dict(_METADATA[stat])


def predict(stat: str, features_dict: dict[str, float]) -> float:
    """Run inference. Features the model expects but aren't in features_dict are filled with 0.0."""
    _ensure_loaded(stat)
    feature_order = _METADATA[stat]["features"]
    vec = np.array([[float(features_dict.get(f, 0.0)) for f in feature_order]])
    model = _MODELS[stat]
    pred = float(model.predict(vec)[0])
    return max(0.0, pred)  # clamp negative predictions to 0
