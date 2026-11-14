"""NHL player shots on goal ML — heuristic baseline + optional XGB shadow (NHL-3.4)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.services.etl.nhl._model_loader import ModelPair
from app.services.ml.train_model import split

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "nhl/ml_models"
MODEL_KEY = "player_sog"
HEURISTIC_VERSION = "heuristic-v1"

_FEATURE_NAMES: tuple[str, ...] = (
    "baseline_shots",
    "ice_time_adjustment",
    "opponent_shots_adjustment",
    "blocks_adjustment",
    "position_adjustment",
    "home_ice_adjustment",
    "player_toi_per_game",
    "opponent_shots_against_pg",
    "opponent_blocks_pg",
    "is_home",
    "is_defenseman",
    "shots_line",
    "heuristic_shots",
)

_PAIR = ModelPair(S3_PREFIX, MODEL_KEY, "NHL_PLAYER_SOG_MODEL_LOCAL")

_TRUTHY = frozenset({"1", "true", "yes"})


def feature_names() -> list[str]:
    return list(_FEATURE_NAMES)


def player_sog_ml_enabled() -> bool:
    return os.getenv("NHL_PLAYER_SOG_ML_ENABLED", "").strip().lower() in _TRUTHY


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_features_from_prediction(prediction: Mapping[str, Any]) -> dict[str, float]:
    """Pure feature vector from ``predict_player_shots`` output (no DB)."""
    baseline = _float_or(prediction.get("baseline_shots"), 0.0)
    position = (prediction.get("player_position") or "").upper()
    return {
        "baseline_shots": baseline,
        "ice_time_adjustment": _float_or(prediction.get("ice_time_adjustment"), 1.0),
        "opponent_shots_adjustment": _float_or(
            prediction.get("opponent_shots_adjustment"), 1.0
        ),
        "blocks_adjustment": _float_or(prediction.get("blocks_adjustment"), 1.0),
        "position_adjustment": _float_or(prediction.get("position_adjustment"), 1.0),
        "home_ice_adjustment": _float_or(prediction.get("home_ice_adjustment"), 1.0),
        "player_toi_per_game": _float_or(prediction.get("player_toi_per_game"), 1000.0),
        "opponent_shots_against_pg": _float_or(
            prediction.get("opponent_shots_against_pg"), 30.0
        ),
        "opponent_blocks_pg": _float_or(prediction.get("opponent_blocks_pg"), 15.0),
        "is_home": 1.0 if prediction.get("is_home") else 0.0,
        "is_defenseman": 1.0 if position == "D" else 0.0,
        "shots_line": 0.0,
        "heuristic_shots": _float_or(prediction.get("predicted_shots"), baseline),
    }


def predict_shots_heuristic(features: Mapping[str, float]) -> float:
    """Same multiplicative stack as ``player_shots_model.predict_player_shots``."""
    baseline = _float_or(features.get("baseline_shots"), 0.0)
    if baseline <= 0:
        return 0.0
    product = (
        _float_or(features.get("ice_time_adjustment"), 1.0)
        * _float_or(features.get("opponent_shots_adjustment"), 1.0)
        * _float_or(features.get("blocks_adjustment"), 1.0)
        * _float_or(features.get("position_adjustment"), 1.0)
        * _float_or(features.get("home_ice_adjustment"), 1.0)
    )
    return round(baseline * product, 2)


def _feature_vector(
    features: Mapping[str, float],
    order: list[str] | None = None,
) -> np.ndarray:
    names = order or feature_names()
    return np.array([[float(features.get(name, 0.0)) for name in names]])


def predict_shots_ml(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    vec = _feature_vector(features, feature_order)
    return round(float(model.predict(vec)[0]), 2)


def train_player_shots_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    hyperparams: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Offline trainer: direct SOG regressor (XGBoost)."""
    import xgboost as xgb
    from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore

    features_df, target = dataset
    if features_df.empty or len(features_df) < 20:
        raise ValueError("insufficient training rows")

    default_hp = {
        "n_estimators": 150,
        "max_depth": 4,
        "learning_rate": 0.08,
        "subsample": 0.85,
        "random_state": 42,
        "objective": "reg:squarederror",
    }
    hp = {**default_hp, **(hyperparams or {})}

    order = feature_names()
    for col in order:
        if col not in features_df.columns:
            features_df[col] = 0.0
    X = features_df[order]
    X_train, X_test, y_train, y_test = split(X, target, chronological=True)
    model = xgb.XGBRegressor(**hp)
    model.fit(X_train, y_train)
    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    train_date = datetime.utcnow().strftime("%Y%m%d")
    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": "actual_shots",
        "trained_at": datetime.utcnow().isoformat(),
        "split": "chronological",
        "train_date": train_date,
        "model_version": f"xgb-sog-{train_date}",
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


def model_available() -> bool:
    return _PAIR.get() is not None


def predict_shots_ml_loaded(features: Mapping[str, float]) -> float | None:
    pair = _PAIR.get()
    if pair is None:
        return None
    model, meta = pair
    order = meta.get("features") or feature_names()
    return predict_shots_ml(model, features, feature_order=list(order))


def resolve_player_sog_model_version(*, ml_loaded: bool) -> str:
    from app.services.ml_model_version import model_version_from_metadata

    pair = _PAIR.get() if ml_loaded else None
    if player_sog_ml_enabled() and pair:
        return model_version_from_metadata(
            pair[1], prefix="xgb-sog", fallback=HEURISTIC_VERSION
        )
    return HEURISTIC_VERSION


def shadow_ml_sog_from_features_used(features_used: Any) -> float | None:
    if not features_used or not isinstance(features_used, dict):
        return None
    val = features_used.get("ml_shadow_sog")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def enrich_player_shots_prediction_for_write(
    prediction: dict[str, Any],
    *,
    shots_line: float | None = None,
    extra_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Shadow enrich: production ``predicted_shots`` stays heuristic unless
    ``NHL_PLAYER_SOG_ML_ENABLED=1`` and model is loaded.
    """
    feats = build_features_from_prediction(prediction)
    if shots_line is not None:
        feats["shots_line"] = float(shots_line)

    heuristic = predict_shots_heuristic(feats)
    prediction = dict(prediction)
    prediction["predicted_shots"] = heuristic
    prediction["heuristic_shots"] = heuristic
    feats["heuristic_shots"] = heuristic

    ml_shots = predict_shots_ml_loaded(feats)
    ml_loaded = ml_shots is not None

    features_used: dict[str, Any] = dict(extra_features or {})
    # Always keep the heuristic: the trainers read it back, so a retrain must
    # never see the ML output instead.
    features_used["heuristic_shots"] = heuristic
    if ml_shots is not None and not player_sog_ml_enabled():
        features_used["ml_shadow_sog"] = ml_shots

    projected = heuristic
    version = resolve_player_sog_model_version(ml_loaded=ml_loaded)
    if player_sog_ml_enabled() and ml_shots is not None:
        projected = ml_shots

    return {
        "predicted_shots": projected,
        "model_version": version,
        "features_used": features_used or None,
        "heuristic_shots": heuristic,
        "ml_shadow_sog": ml_shots,
    }
