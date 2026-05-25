"""NHL team totals goals ML — heuristic baseline + residual GBM shadow (NHL-3.4)."""

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

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "nhl/ml_models"
MODEL_KEY = "team_totals"
HEURISTIC_VERSION = "heuristic-v1"

_FEATURE_NAMES: tuple[str, ...] = (
    "heuristic_total",
    "predicted_home_goals",
    "predicted_away_goals",
    "home_offense_rating",
    "away_offense_rating",
    "home_defense_rating",
    "away_defense_rating",
    "combined_pace",
    "home_pp_pct",
    "away_pp_pct",
    "home_pk_pct",
    "away_pk_pct",
    "suggested_ou_line",
    "market_ou_line",
)

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


def feature_names() -> list[str]:
    return list(_FEATURE_NAMES)


def totals_ml_enabled() -> bool:
    return os.getenv("NHL_TOTALS_ML_ENABLED", "").strip().lower() in _TRUTHY


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_features_from_prediction(prediction: Mapping[str, Any]) -> dict[str, float]:
    """Pure feature vector from ``predict_team_total_goals`` output (no DB)."""
    heuristic = _float_or(
        prediction.get("predicted_total_goals"),
        _float_or(prediction.get("heuristic_total"), 6.0),
    )
    market = prediction.get("draftkings_ou_line") or prediction.get("market_ou_line")
    return {
        "heuristic_total": heuristic,
        "predicted_home_goals": _float_or(prediction.get("predicted_home_goals"), 3.0),
        "predicted_away_goals": _float_or(prediction.get("predicted_away_goals"), 3.0),
        "home_offense_rating": _float_or(prediction.get("home_offense_rating"), 3.0),
        "away_offense_rating": _float_or(prediction.get("away_offense_rating"), 3.0),
        "home_defense_rating": _float_or(prediction.get("home_defense_rating"), 3.0),
        "away_defense_rating": _float_or(prediction.get("away_defense_rating"), 3.0),
        "combined_pace": _float_or(prediction.get("combined_pace"), 60.0),
        "home_pp_pct": _float_or(prediction.get("home_pp_pct"), 20.0),
        "away_pp_pct": _float_or(prediction.get("away_pp_pct"), 20.0),
        "home_pk_pct": _float_or(prediction.get("home_pk_pct"), 80.0),
        "away_pk_pct": _float_or(prediction.get("away_pk_pct"), 80.0),
        "suggested_ou_line": _float_or(prediction.get("suggested_ou_line"), heuristic),
        "market_ou_line": _float_or(market, 0.0),
    }


def predict_total_heuristic(features: Mapping[str, float]) -> float:
    """Delegate to stored heuristic total (recomputed from game model output)."""
    return round(_float_or(features.get("heuristic_total"), 6.0), 2)


def _feature_vector(
    features: Mapping[str, float],
    order: list[str] | None = None,
) -> np.ndarray:
    names = order or feature_names()
    return np.array([[float(features.get(name, 0.0)) for name in names]])


def predict_total_residual(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    vec = _feature_vector(features, feature_order)
    return float(model.predict(vec)[0])


def predict_total_ml(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    heuristic = predict_total_heuristic(features)
    residual = predict_total_residual(model, features, feature_order=feature_order)
    return round(heuristic + residual, 2)


def train_team_totals_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    hyperparams: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """
    Offline trainer: residual target ``actual_total - heuristic_total``.

    Uses sklearn GradientBoostingRegressor (NBA totals pattern).
    """
    from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
    from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore

    features_df, target = dataset
    if features_df.empty or len(features_df) < 20:
        raise ValueError("insufficient training rows")

    default_hp = {
        "n_estimators": 150,
        "max_depth": 4,
        "learning_rate": 0.08,
        "subsample": 0.85,
        "random_state": 42,
    }
    hp = {**default_hp, **(hyperparams or {})}

    order = feature_names()
    for col in order:
        if col not in features_df.columns:
            features_df[col] = 0.0
    X = features_df[order]
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
        "target": "residual_actual_minus_heuristic",
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": f"gbm-totals-{train_date}",
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
    base = os.getenv("NHL_TOTALS_MODEL_LOCAL", "").strip()
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
                        f"NHL team totals model missing under {model_path.parent}"
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
            logger.info("NHL team totals ML model unavailable: %s", exc)
            _LOAD_FAILED = True
            return False


def model_available() -> bool:
    return _ensure_loaded()


def predict_total_ml_loaded(features: Mapping[str, float]) -> float | None:
    if not _ensure_loaded() or _MODEL is None:
        return None
    order = (_METADATA or {}).get("features") or feature_names()
    return predict_total_ml(_MODEL, features, feature_order=list(order))


def resolve_totals_model_version(*, ml_loaded: bool) -> str:
    from app.services.ml_model_version import model_version_from_metadata

    if totals_ml_enabled() and ml_loaded and _METADATA:
        return model_version_from_metadata(
            _METADATA, prefix="gbm-totals", fallback=HEURISTIC_VERSION
        )
    return HEURISTIC_VERSION


def shadow_ml_total_from_features_used(features_used: Any) -> float | None:
    if not features_used or not isinstance(features_used, dict):
        return None
    val = features_used.get("ml_shadow_total")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def enrich_team_totals_prediction_for_write(
    prediction: dict[str, Any],
    *,
    draftkings_ou_line: float | None = None,
    extra_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Shadow enrich: production ``predicted_total_goals`` stays heuristic unless
    ``NHL_TOTALS_ML_ENABLED=1`` and model is loaded.
    """
    prediction = dict(prediction)
    if draftkings_ou_line is not None:
        prediction["draftkings_ou_line"] = draftkings_ou_line

    feats = build_features_from_prediction(prediction)
    heuristic = predict_total_heuristic(feats)
    prediction["predicted_total_goals"] = heuristic
    prediction["heuristic_total"] = heuristic
    feats["heuristic_total"] = heuristic

    ml_total = predict_total_ml_loaded(feats)
    ml_loaded = ml_total is not None

    features_used: dict[str, Any] = dict(extra_features or {})
    if ml_total is not None and not totals_ml_enabled():
        features_used["ml_shadow_total"] = ml_total
        features_used["heuristic_total"] = heuristic

    projected = heuristic
    version = resolve_totals_model_version(ml_loaded=ml_loaded)
    if totals_ml_enabled() and ml_total is not None:
        projected = ml_total

    out = dict(prediction)
    out["predicted_total_goals"] = projected
    out["model_version"] = version
    out["features_used"] = features_used or None
    out["heuristic_total"] = heuristic
    out["ml_shadow_total"] = ml_total
    return out
