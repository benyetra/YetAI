"""NFL QB passing yards ML — tier heuristic baseline + optional GBM shadow (NFL-4.3)."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our own private bucket
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_features import (
    FEATURE_NAMES,
    build_qb_features,
    feature_names as qb_feature_names,
)

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "nfl/ml_models"
MODEL_KEY = "qb_passing_yards"
TIER_VERSION = "tier-v2"

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


def feature_names() -> list[str]:
    return qb_feature_names()


def qb_ml_enabled() -> bool:
    return os.getenv("NFL_QB_ML_ENABLED", "").strip().lower() in _TRUTHY


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_features_from_tier_prediction(
    prediction: Mapping[str, Any],
    *,
    season: int,
    week: int,
    is_backup: bool = False,
    context: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Build GBM features from tier prediction + optional matchup/form context."""
    tier_yards = _float_or(prediction.get("predicted_passing_yards"), 210.0)
    return build_qb_features(
        tier_yards=tier_yards,
        season=season,
        week=week,
        is_backup=is_backup,
        confidence=_float_or(prediction.get("confidence"), 0.65),
        context=context,
    )


def predict_yards_tier(features: Mapping[str, float]) -> float:
    return round(_float_or(features.get("tier_yards"), 210.0), 1)


def _feature_vector(
    features: Mapping[str, float],
    order: list[str] | None = None,
) -> np.ndarray:
    names = order or feature_names()
    return np.array([[float(features.get(name, 0.0)) for name in names]])


def predict_yards_ml(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    """GBM predicts passing yards directly (trained with tier_yards as strong feature)."""
    vec = _feature_vector(features, feature_order)
    return round(float(model.predict(vec)[0]), 1)


def train_qb_yards_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    hyperparams: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
    from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore

    features_df, target = dataset
    if features_df.empty or len(features_df) < 30:
        raise ValueError("insufficient training rows")

    default_hp = {
        "n_estimators": 120,
        "max_depth": 4,
        "learning_rate": 0.08,
        "subsample": 0.85,
        "random_state": 42,
    }
    hp = {**default_hp, **(hyperparams or {})}

    order = feature_names()
    # Older artifacts / partial frames may omit newer columns — fill priors via
    # build_qb_features defaults rather than raw zeros.
    for col in order:
        if col not in features_df.columns:
            if col in ("is_home",):
                features_df[col] = 0.5
            elif col in ("rest_days",):
                features_df[col] = 7.0
            elif col in (
                "opp_pass_yds_allowed",
                "rolling_yards_l3",
                "rolling_yards_l5",
                "season_avg_yards",
            ):
                features_df[col] = features_df.get("tier_yards", 220.0)
            elif col == "implied_team_total":
                features_df[col] = 22.5
            elif col == "temperature":
                features_df[col] = 65.0
            elif col == "wind_speed":
                features_df[col] = 5.0
            else:
                features_df[col] = 0.0
    X = features_df[list(order)]
    X_train, X_test, y_train, y_test = train_test_split(
        X, target, test_size=0.2, random_state=42
    )
    model = GradientBoostingRegressor(**hp)
    model.fit(X_train, y_train)
    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    train_date = datetime.utcnow().strftime("%Y%m%d")
    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": "actual_passing_yards",
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": f"gbm-qb-yards-{train_date}",
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": order,
        "hyperparams": hp,
        "train_mae": float(mean_absolute_error(y_train, y_pred_train)),
        "test_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "holdout_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, y_pred_train))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
    }
    logger.info(
        "trained %s: train_mae=%.3f test_mae=%.3f",
        MODEL_KEY,
        metadata["train_mae"],
        metadata["test_mae"],
    )
    return model, metadata


def _local_model_paths() -> tuple[Path, Path] | None:
    base = os.getenv("NFL_QB_MODEL_LOCAL", "").strip()
    if not base:
        return None
    root = Path(base)
    return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"


def _download_artifact(s3_key: str, local_path: Path) -> None:
    import boto3

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
            local = _local_model_paths()
            if local is not None:
                model_path, meta_path = local
                if not model_path.is_file() or not meta_path.is_file():
                    raise FileNotFoundError(
                        f"NFL QB model missing under {model_path.parent}"
                    )
                with model_path.open("rb") as f:
                    _MODEL = pickle.load(f)  # nosec B301
                _METADATA = json.loads(meta_path.read_text())
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    model_local = tmp / f"{MODEL_KEY}.pkl"
                    meta_local = tmp / f"{MODEL_KEY}_metadata.json"
                    _download_artifact(f"{S3_PREFIX}/{MODEL_KEY}.pkl", model_local)
                    _download_artifact(
                        f"{S3_PREFIX}/{MODEL_KEY}_metadata.json", meta_local
                    )
                    with model_local.open("rb") as f:
                        _MODEL = pickle.load(f)  # nosec B301
                    _METADATA = json.loads(meta_local.read_text())
            return True
        except Exception as exc:
            logger.info("NFL QB yards ML model unavailable: %s", exc)
            _LOAD_FAILED = True
            return False


def model_available() -> bool:
    return _ensure_loaded()


def predict_yards_ml_loaded(features: Mapping[str, float]) -> float | None:
    if not _ensure_loaded() or _MODEL is None:
        return None
    order = (_METADATA or {}).get("features") or feature_names()
    return predict_yards_ml(_MODEL, features, feature_order=list(order))


def resolve_qb_model_version(*, ml_loaded: bool) -> str:
    from app.services.ml_model_version import model_version_from_metadata

    if qb_ml_enabled() and ml_loaded and _METADATA:
        return model_version_from_metadata(
            _METADATA, prefix="gbm-qb-yards", fallback=TIER_VERSION
        )
    return TIER_VERSION


def shadow_ml_yards_from_feature_importance(feature_importance: Any) -> float | None:
    if not feature_importance or not isinstance(feature_importance, dict):
        return None
    val = feature_importance.get("ml_shadow_yards")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def enrich_qb_prediction_for_write(
    prediction: dict[str, Any],
    *,
    season: int,
    week: int,
    is_backup: bool = False,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Shadow enrich: production yards stay tier table unless ``NFL_QB_ML_ENABLED=1``.

    ``context`` carries matchup/form features (rolling yards, opp pass D, home,
    rest, implied total, weather). See ``qb_features.build_qb_features``.
    """
    feats = build_features_from_tier_prediction(
        prediction,
        season=season,
        week=week,
        is_backup=is_backup,
        context=context,
    )
    tier_yards = predict_yards_tier(feats)
    prediction = dict(prediction)
    prediction["predicted_passing_yards"] = tier_yards

    ml_yards = predict_yards_ml_loaded(feats)
    ml_loaded = ml_yards is not None

    feature_importance: dict[str, Any] = {
        "tier_yards": tier_yards,
        "prediction_method": prediction.get("prediction_method"),
        "features": {k: feats.get(k) for k in FEATURE_NAMES},
    }
    if ml_yards is not None and not qb_ml_enabled():
        feature_importance["ml_shadow_yards"] = ml_yards

    projected = tier_yards
    version = resolve_qb_model_version(ml_loaded=ml_loaded)
    method = prediction.get("prediction_method") or "tier_table"
    if qb_ml_enabled() and ml_yards is not None:
        projected = ml_yards
        method = "gbm_qb_yards"

    return {
        "predicted_passing_yards": projected,
        "model_confidence": prediction.get("confidence"),
        "prediction_method": method,
        "model_version": version,
        "feature_importance": feature_importance,
        "tier_yards": tier_yards,
        "ml_shadow_yards": ml_yards,
        "feature_context": feats,
    }
