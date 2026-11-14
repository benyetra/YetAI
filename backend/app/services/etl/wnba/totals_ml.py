"""WNBA game totals ML — residual GBM on heuristic baseline (NBA parity port)."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our own private bucket
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.services.ml.model_store import S3Object
from app.services.ml_model_version import model_version_from_metadata

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "wnba/ml_models"
MODEL_KEY = "gbm_totals_residual"

_FEATURE_NAMES: tuple[str, ...] = (
    "heuristic_total",
    "base_projection",
    "expected_pace",
    "home_offensive_rating",
    "away_offensive_rating",
    "home_defensive_rating",
    "away_defensive_rating",
    "injury_adjustment",
    "rest_adjustment",
    "venue_adjustment",
    "form_adjustment",
    "total_adjustment",
    "market_total",
    "market_minus_heuristic",
)

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_OBJECTS: tuple[S3Object, S3Object] | None = None
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


def feature_names() -> list[str]:
    return list(_FEATURE_NAMES)


def features_from_projection(projection: dict[str, Any]) -> dict[str, float]:
    """Build model input vector from a totals_projector projection dict."""
    heuristic = float(
        projection.get("heuristic_total") or projection.get("projected_total") or 0.0
    )
    market = projection.get("market_total")
    market_f = float(market) if market is not None else 0.0
    return {
        "heuristic_total": heuristic,
        "base_projection": float(projection.get("base_projection") or 0.0),
        "expected_pace": float(projection.get("expected_pace") or 0.0),
        "home_offensive_rating": float(projection.get("home_offensive_rating") or 0.0),
        "away_offensive_rating": float(projection.get("away_offensive_rating") or 0.0),
        "home_defensive_rating": float(projection.get("home_defensive_rating") or 0.0),
        "away_defensive_rating": float(projection.get("away_defensive_rating") or 0.0),
        "injury_adjustment": float(projection.get("injury_adjustment") or 0.0),
        "rest_adjustment": float(projection.get("rest_adjustment") or 0.0),
        "venue_adjustment": float(projection.get("venue_adjustment") or 0.0),
        "form_adjustment": float(projection.get("form_adjustment") or 0.0),
        "total_adjustment": float(projection.get("total_adjustment") or 0.0),
        "market_total": market_f,
        "market_minus_heuristic": market_f - heuristic if market is not None else 0.0,
    }


def totals_ml_enabled() -> bool:
    return os.getenv("WNBA_TOTALS_ML_ENABLED", "").strip().lower() in _TRUTHY


def _local_model_paths() -> tuple[Path, Path] | None:
    base = os.getenv("WNBA_TOTALS_MODEL_LOCAL", "").strip()
    if not base:
        return None
    root = Path(base)
    return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"


def _s3_objects() -> tuple[S3Object, S3Object]:
    global _OBJECTS
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


def _ensure_loaded() -> bool:
    """Local override files load once; the S3 model refreshes on the shared
    interval, keeps the last good copy on failure, and is never sticky."""
    global _MODEL, _METADATA
    with _LOCK:
        local = _local_model_paths()
        if local is None:
            model_obj, meta_obj = _s3_objects()
            _MODEL, _METADATA = model_obj.get(), meta_obj.get()
            return _MODEL is not None and _METADATA is not None
        if _MODEL is not None and _METADATA is not None:
            return True
        try:
            model_path, meta_path = local
            if not model_path.is_file() or not meta_path.is_file():
                raise FileNotFoundError(
                    f"WNBA totals model missing under {model_path.parent}"
                )
            with model_path.open("rb") as f:
                _MODEL = pickle.load(f)  # nosec B301
            _METADATA = json.loads(meta_path.read_text())
            return True
        except Exception as exc:
            logger.info("WNBA totals ML model unavailable: %s", exc)
            return False


def model_available() -> bool:
    return _ensure_loaded()


def predict_residual(features_dict: dict[str, float]) -> float | None:
    """Predict (actual_total - heuristic_total); None if model not loaded."""
    if not _ensure_loaded() or _MODEL is None or _METADATA is None:
        return None
    order = _METADATA.get("features") or feature_names()
    vec = np.array([[float(features_dict.get(f, 0.0)) for f in order]])
    return float(_MODEL.predict(vec)[0])


def _recompute_market_fields(projection: dict[str, Any]) -> None:
    """Refresh edge / recommendation after projected_total changes."""
    market_total = projection.get("market_total")
    projected_total = projection.get("projected_total")
    if market_total is None or projected_total is None:
        return
    edge = float(projected_total) - float(market_total)
    projection["edge"] = round(edge, 1)
    if edge > 2:
        projection["recommendation"] = "OVER"
        projection["confidence_score"] = round(min(0.5 + (abs(edge) * 0.05), 0.85), 2)
    elif edge < -2:
        projection["recommendation"] = "UNDER"
        projection["confidence_score"] = round(min(0.5 + (abs(edge) * 0.05), 0.85), 2)
    else:
        projection["recommendation"] = "NO_PLAY"
        projection["confidence_score"] = 0.5


def enrich_projection(projection: dict[str, Any]) -> dict[str, Any]:
    """
    Attach heuristic_total, optional ml_total, and ml_shadow in factors.

    Production ``projected_total`` stays heuristic unless WNBA_TOTALS_ML_ENABLED=1
    and a model is loaded.
    """
    heuristic = float(projection["projected_total"])
    projection["heuristic_total"] = round(heuristic, 1)

    feats = features_from_projection(projection)
    residual = predict_residual(feats)
    ml_total = None
    if residual is not None:
        ml_total = round(heuristic + residual, 1)
    projection["ml_total"] = ml_total

    factors = dict(projection.get("factors") or {})
    factors["ml_shadow"] = {
        "heuristic_total": projection["heuristic_total"],
        "ml_total": ml_total,
        "residual_pred": round(residual, 2) if residual is not None else None,
        "ml_enabled": totals_ml_enabled() and ml_total is not None,
    }
    projection["factors"] = factors

    if ml_total is not None:
        logger.info(
            "WNBA totals ML shadow %s @ %s: heuristic=%.1f ml=%.1f residual=%+.1f",
            projection.get("away_team"),
            projection.get("home_team"),
            heuristic,
            ml_total,
            residual or 0.0,
        )

    projection["model_version"] = "heuristic-v1"
    if totals_ml_enabled() and ml_total is not None:
        projection["projected_total"] = ml_total
        _recompute_market_fields(projection)
        manifest_version = None if _local_model_paths() else _s3_objects()[0].version
        projection["model_version"] = manifest_version or model_version_from_metadata(
            _METADATA, prefix="xgb", fallback="xgb-totals-v1"
        )

    return projection


def shadow_from_factors(factors: dict | None) -> dict[str, float | None]:
    """Read heuristic/ml totals stored in projection.factors JSON."""
    if not factors or not isinstance(factors, dict):
        return {"heuristic_total": None, "ml_total": None}
    shadow = factors.get("ml_shadow") or {}
    if not isinstance(shadow, dict):
        return {"heuristic_total": None, "ml_total": None}
    return {
        "heuristic_total": shadow.get("heuristic_total"),
        "ml_total": shadow.get("ml_total"),
    }
