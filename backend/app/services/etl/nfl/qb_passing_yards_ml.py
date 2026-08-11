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
TIER_VERSION = "tier-v3"

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


def _model_is_residual(metadata: Mapping[str, Any] | None) -> bool:
    """True when artifact predicts residual (actual − tier), the current default."""
    if not metadata:
        return True
    target = str(metadata.get("target") or "").lower()
    if "residual" in target:
        return True
    if target in {"actual_passing_yards", "passing_yards"}:
        return False
    # Prefer residual for unknown / new artifacts
    return bool(metadata.get("residual_target", True))


def predict_yards_residual(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    """Raw residual prediction (actual − tier)."""
    vec = _feature_vector(features, feature_order)
    return float(model.predict(vec)[0])


def predict_yards_ml(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
    residual_target: bool = True,
) -> float:
    """
    GBM yards: ``tier + residual`` (default) or direct yards for legacy artifacts.
    """
    raw = predict_yards_residual(model, features, feature_order=feature_order)
    if residual_target:
        tier = predict_yards_tier(features)
        return round(tier + raw, 1)
    return round(float(raw), 1)


def _fill_missing_feature_columns(features_df: pd.DataFrame) -> pd.DataFrame:
    """Fill priors for missing columns (older frames / partial context)."""
    order = feature_names()
    for col in order:
        if col in features_df.columns:
            continue
        if col in ("is_home",):
            features_df[col] = 0.5
        elif col in ("rest_days",):
            features_df[col] = 7.0
        elif col in (
            "opp_pass_yds_allowed",
            "rolling_yards_l3",
            "rolling_yards_l5",
            "season_avg_yards",
            "pass_yds_line",
        ):
            features_df[col] = features_df.get("tier_yards", 220.0)
        elif col == "opp_def_epa":
            features_df[col] = 0.0
        elif col == "opp_pressure_rate":
            features_df[col] = 0.25
        elif col == "injury_risk":
            features_df[col] = 0.0
        elif col == "implied_team_total":
            features_df[col] = 22.5
        elif col == "total_line":
            features_df[col] = 45.0
        elif col == "spread_line":
            features_df[col] = 0.0
        elif col == "temperature":
            features_df[col] = 65.0
        elif col == "wind_speed":
            features_df[col] = 5.0
        elif col == "opp_cover_base":
            features_df[col] = 3.0
        elif col == "opp_man_zone":
            features_df[col] = 0.0
        elif col == "opp_scheme_pressure":
            features_df[col] = 0.5
        else:
            features_df[col] = 0.0
    return features_df


def train_qb_yards_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    hyperparams: dict[str, Any] | None = None,
    residual_target: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """
    Train GBM on residual ``actual − tier_yards`` (default) or direct yards.

    When ``residual_target`` is True, ``dataset`` target must be actual yards;
    residuals are derived from the ``tier_yards`` column.
    """
    from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
    from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore

    features_df, target = dataset
    if features_df.empty or len(features_df) < 30:
        raise ValueError("insufficient training rows")

    default_hp = {
        "n_estimators": 150,
        "max_depth": 3,
        "learning_rate": 0.06,
        "subsample": 0.85,
        "random_state": 42,
        "min_samples_leaf": 8,
    }
    hp = {**default_hp, **(hyperparams or {})}

    order = feature_names()
    features_df = _fill_missing_feature_columns(features_df.copy())
    X = features_df[list(order)]
    if residual_target:
        tier = features_df["tier_yards"].astype(float)
        y = (target.astype(float) - tier).astype(float)
    else:
        y = target.astype(float)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    model = GradientBoostingRegressor(**hp)
    model.fit(X_train, y_train)
    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    # Report MAE on yards scale (tier + residual) for residual models
    if residual_target:
        tier_train = X_train["tier_yards"].to_numpy()
        tier_test = X_test["tier_yards"].to_numpy()
        train_yards_mae = float(
            mean_absolute_error(y_train + tier_train, y_pred_train + tier_train)
        )
        test_yards_mae = float(
            mean_absolute_error(y_test + tier_test, y_pred_test + tier_test)
        )
        train_rmse = float(
            np.sqrt(mean_squared_error(y_train + tier_train, y_pred_train + tier_train))
        )
        test_rmse = float(
            np.sqrt(mean_squared_error(y_test + tier_test, y_pred_test + tier_test))
        )
    else:
        train_yards_mae = float(mean_absolute_error(y_train, y_pred_train))
        test_yards_mae = float(mean_absolute_error(y_test, y_pred_test))
        train_rmse = float(np.sqrt(mean_squared_error(y_train, y_pred_train)))
        test_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_test)))

    train_date = datetime.utcnow().strftime("%Y%m%d")
    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": (
            "residual_actual_minus_tier" if residual_target else "actual_passing_yards"
        ),
        "residual_target": bool(residual_target),
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": (
            f"gbm-qb-residual-{train_date}"
            if residual_target
            else f"gbm-qb-yards-{train_date}"
        ),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": order,
        "hyperparams": hp,
        "train_mae": train_yards_mae,
        "test_mae": test_yards_mae,
        "holdout_mae": test_yards_mae,
        "train_rmse": train_rmse,
        "test_rmse": test_rmse,
        "train_residual_mae": float(mean_absolute_error(y_train, y_pred_train)),
        "test_residual_mae": float(mean_absolute_error(y_test, y_pred_test)),
    }
    logger.info(
        "trained %s: train_mae=%.3f test_mae=%.3f residual=%s",
        MODEL_KEY,
        metadata["train_mae"],
        metadata["test_mae"],
        residual_target,
    )
    return model, metadata


def _bundled_model_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[4] / "models" / "nfl"
    return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"


def _local_model_paths() -> tuple[Path, Path] | None:
    base = os.getenv("NFL_QB_MODEL_LOCAL", "").strip()
    if base:
        root = Path(base)
        return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"
    # Fall back to shipped backend/models/nfl artifacts (same pattern as kickers)
    model_path, meta_path = _bundled_model_paths()
    if model_path.is_file() and meta_path.is_file():
        return model_path, meta_path
    return None


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
    residual = _model_is_residual(_METADATA)
    return predict_yards_ml(
        _MODEL,
        features,
        feature_order=list(order),
        residual_target=residual,
    )


def resolve_qb_model_version(*, ml_loaded: bool) -> str:
    from app.services.ml_model_version import model_version_from_metadata

    if qb_ml_enabled() and ml_loaded and _METADATA:
        prefix = "gbm-qb-residual" if _model_is_residual(_METADATA) else "gbm-qb-yards"
        return model_version_from_metadata(
            _METADATA, prefix=prefix, fallback=TIER_VERSION
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
        method = "gbm_qb_residual" if _model_is_residual(_METADATA) else "gbm_qb_yards"

    # Prediction intervals: prefer explicit tier intervals; widen slightly for ML
    lower = prediction.get("prediction_interval_lower")
    upper = prediction.get("prediction_interval_upper")
    if lower is None or upper is None:
        half = 35.0
        lower = max(120.0, projected - half)
        upper = min(380.0, projected + half)
    elif qb_ml_enabled() and ml_yards is not None:
        # Recenter interval on ML point estimate, keep width
        width = (float(upper) - float(lower)) / 2.0
        lower = max(120.0, projected - width)
        upper = min(380.0, projected + width)

    return {
        "predicted_passing_yards": projected,
        "model_confidence": prediction.get("confidence"),
        "prediction_method": method,
        "model_version": version,
        "feature_importance": feature_importance,
        "tier_yards": tier_yards,
        "ml_shadow_yards": ml_yards,
        "feature_context": feats,
        "prediction_interval_lower": round(float(lower), 1),
        "prediction_interval_upper": round(float(upper), 1),
    }
