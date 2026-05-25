"""NHL goalie saves ML — heuristic baseline + optional XGB shadow (NHL-3.3)."""

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
MODEL_KEY = "goalie_saves"
HEURISTIC_VERSION = "heuristic-v1"

_FEATURE_NAMES: tuple[str, ...] = (
    "recent_sv_pct",
    "season_sv_pct",
    "home_away_sv_pct",
    "opponent_shots_avg",
    "predicted_shots_against",
    "weighted_sv_pct",
    "is_home",
    "days_rest",
    "rest_back_to_back",
    "team_defense_shots",
    "saves_line",
    "heuristic_saves",
)

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


def feature_names() -> list[str]:
    return list(_FEATURE_NAMES)


def goalie_ml_enabled() -> bool:
    return os.getenv("NHL_GOALIE_ML_ENABLED", "").strip().lower() in _TRUTHY


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_features_from_prediction(prediction: Mapping[str, Any]) -> dict[str, float]:
    """
    Pure feature vector from ``predict_goalie_saves`` output (no DB).

    Uses the same core inputs as the heuristic path: recent SV%, opponent shots,
    rest, home, and blended save percentage / shots against.
    """
    recent = prediction.get("goalie_recent_sv_pct")
    season = prediction.get("goalie_season_sv_pct") or prediction.get(
        "predicted_save_pct"
    )

    home_away = prediction.get("home_away_sv_pct")
    opponent_shots = prediction.get("opponent_shots_avg")
    predicted_shots = prediction.get("predicted_shots_against")
    weighted_sv = prediction.get("predicted_save_pct")

    recent_f = _float_or(recent, _float_or(season, 0.905))
    season_f = _float_or(season, recent_f)
    shots = _float_or(
        predicted_shots,
        _float_or(opponent_shots, 30.0),
    )
    weighted = _float_or(weighted_sv, recent_f)

    rest_cat = prediction.get("rest_category") or ""
    days_rest = prediction.get("days_rest")
    is_b2b = 1.0 if rest_cat == "back_to_back" else 0.0
    if prediction.get("is_back_to_back"):
        is_b2b = 1.0

    team_def = prediction.get("opponent_shots_avg")
    if prediction.get("team_defense_shots"):
        team_def = prediction.get("team_defense_shots")

    return {
        "recent_sv_pct": recent_f,
        "season_sv_pct": season_f,
        "home_away_sv_pct": _float_or(home_away, recent_f),
        "opponent_shots_avg": _float_or(opponent_shots, shots),
        "predicted_shots_against": shots,
        "weighted_sv_pct": weighted,
        "is_home": 1.0 if prediction.get("is_home") else 0.0,
        "days_rest": _float_or(days_rest, 1.0),
        "rest_back_to_back": is_b2b,
        "team_defense_shots": _float_or(team_def, shots),
        "saves_line": 0.0,
        "heuristic_saves": _float_or(
            prediction.get("predicted_saves"), shots * weighted
        ),
    }


def predict_saves_heuristic(features: Mapping[str, float]) -> float:
    """Core saves estimate: shots against × blended save percentage."""
    shots = _float_or(
        features.get("predicted_shots_against"),
        _float_or(features.get("opponent_shots_avg"), 30.0),
    )
    sv = _float_or(
        features.get("weighted_sv_pct"),
        _float_or(
            features.get("recent_sv_pct"),
            _float_or(features.get("season_sv_pct"), 0.905),
        ),
    )
    return round(shots * sv, 1)


def _feature_vector(
    features: Mapping[str, float],
    order: list[str] | None = None,
) -> np.ndarray:
    names = order or feature_names()
    return np.array([[float(features.get(name, 0.0)) for name in names]])


def predict_saves_ml(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    """Regressor predict for goalie saves (direct target, not residual)."""
    vec = _feature_vector(features, feature_order)
    return round(float(model.predict(vec)[0]), 1)


def train_goalie_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    hyperparams: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """
    Offline trainer: ``dataset`` is (features_df, actual_saves Series).

    Uses sklearn GradientBoostingRegressor (same stack as NBA totals training).
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
        "target": "actual_saves",
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": f"xgb-goalie-{train_date}",
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
    base = os.getenv("NHL_GOALIE_MODEL_LOCAL", "").strip()
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
                        f"NHL goalie model missing under {model_path.parent}"
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
            logger.info("NHL goalie saves ML model unavailable: %s", exc)
            _LOAD_FAILED = True
            return False


def model_available() -> bool:
    return _ensure_loaded()


def predict_saves_ml_loaded(features: Mapping[str, float]) -> float | None:
    if not _ensure_loaded() or _MODEL is None:
        return None
    order = (_METADATA or {}).get("features") or feature_names()
    return predict_saves_ml(_MODEL, features, feature_order=list(order))


def resolve_goalie_model_version(*, ml_loaded: bool) -> str:
    from app.services.ml_model_version import model_version_from_metadata

    if goalie_ml_enabled() and ml_loaded and _METADATA:
        return model_version_from_metadata(
            _METADATA, prefix="xgb-goalie", fallback=HEURISTIC_VERSION
        )
    return HEURISTIC_VERSION


def shadow_ml_saves_from_features_used(features_used: Any) -> float | None:
    if not features_used or not isinstance(features_used, dict):
        return None
    val = features_used.get("ml_shadow_saves")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def enrich_goalie_prediction_for_write(
    prediction: dict[str, Any],
    starter_metadata: dict[str, Any] | None = None,
    *,
    saves_line: float | None = None,
) -> dict[str, Any]:
    """
    Shadow enrich: production ``predicted_saves`` stays heuristic unless
    ``NHL_GOALIE_ML_ENABLED=1`` and model is loaded.
    """
    feats = build_features_from_prediction(prediction)
    if saves_line is not None:
        feats["saves_line"] = float(saves_line)

    heuristic = predict_saves_heuristic(feats)
    prediction = dict(prediction)
    prediction["predicted_saves"] = heuristic
    prediction["heuristic_saves"] = heuristic
    feats["heuristic_saves"] = heuristic

    ml_saves = predict_saves_ml_loaded(feats)
    ml_loaded = ml_saves is not None

    features_used: dict[str, Any] = dict(starter_metadata or {})
    if ml_saves is not None and not goalie_ml_enabled():
        features_used["ml_shadow_saves"] = ml_saves
        features_used["heuristic_saves"] = heuristic

    projected = heuristic
    version = resolve_goalie_model_version(ml_loaded=ml_loaded)
    if goalie_ml_enabled() and ml_saves is not None:
        projected = ml_saves

    return {
        "predicted_saves": projected,
        "model_version": version,
        "features_used": features_used or None,
        "heuristic_saves": heuristic,
        "ml_shadow_saves": ml_saves,
    }
