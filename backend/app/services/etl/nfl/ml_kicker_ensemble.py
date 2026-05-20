"""
Optional NFL kicker FG ensemble — local backend/models/nfl or S3 prefix.

Set NFL_MODELS_S3_PREFIX=s3://yetibets/nfl/ on Railway to avoid shipping large pickles
in the image (local copies remain the dev fallback).
"""

from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import joblib

from app.services.etl.nfl.ml_feature_mapping import get_feature_mapper

logger = logging.getLogger(__name__)

_LOCAL_MODEL_DIR = Path(__file__).resolve().parents[4] / "models" / "nfl"
_MODEL_FILES = {
    "logistic": "logistic_model.pkl",
    "random_forest": "random_forest_model.pkl",
    "gradient_boosting": "gradient_boosting_model.pkl",
    "xgboost": "xgboost_model.pkl",
}
_SCALER_FILE = "main_scaler.pkl"


def _normalize_s3_prefix(prefix: str) -> str:
    p = prefix.strip().rstrip("/")
    if not p:
        return ""
    if not p.startswith("s3://"):
        p = f"s3://{p}"
    return p


def _resolve_model_uri(filename: str) -> str:
    """Local path or s3:// URI for one artifact."""
    s3_prefix = _normalize_s3_prefix(os.getenv("NFL_MODELS_S3_PREFIX", ""))
    if s3_prefix:
        return f"{s3_prefix}/{filename}"
    return str(_LOCAL_MODEL_DIR / filename)


def _load_joblib(path: str) -> Any:
    if path.startswith("s3://"):
        import boto3

        parts = path[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return joblib.load(BytesIO(body))
    return joblib.load(path)


class MLKickerEnsemble:
    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.scalers: dict[str, Any] = {}
        self.feature_mapper = get_feature_mapper()
        self.model_source: str = "none"
        self._load()

    def _load(self) -> None:
        s3_prefix = _normalize_s3_prefix(os.getenv("NFL_MODELS_S3_PREFIX", ""))
        self.model_source = s3_prefix if s3_prefix else str(_LOCAL_MODEL_DIR)

        for name, filename in _MODEL_FILES.items():
            uri = _resolve_model_uri(filename)
            try:
                if not uri.startswith("s3://") and not Path(uri).exists():
                    continue
                self.models[name] = _load_joblib(uri)
                logger.info("Loaded NFL kicker model %s from %s", name, uri)
            except Exception as exc:
                logger.warning(
                    "Could not load NFL model %s from %s: %s", name, uri, exc
                )

        scaler_uri = _resolve_model_uri(_SCALER_FILE)
        try:
            if scaler_uri.startswith("s3://") or Path(scaler_uri).exists():
                self.scalers["main"] = _load_joblib(scaler_uri)
                logger.info("Loaded NFL kicker scaler from %s", scaler_uri)
        except Exception as exc:
            logger.warning("Could not load NFL scaler from %s: %s", scaler_uri, exc)

    @property
    def available(self) -> bool:
        return bool(self.models)

    def predict_success_probability(
        self,
        kicker_data: dict,
        team_data: dict,
        weather_data: dict | None = None,
        game_context: dict | None = None,
        model_name: str = "gradient_boosting",
    ) -> float | None:
        if model_name not in self.models:
            model_name = next(iter(self.models), None)
        if not model_name:
            return None

        df_orig, df_mapped = self.feature_mapper.prepare_prediction_features(
            kicker_data, team_data, weather_data, game_context
        )
        model = self.models[model_name]
        if model_name == "logistic" and "main" in self.scalers:
            x = self.scalers["main"].transform(df_orig)
        elif model_name == "xgboost":
            x = df_mapped
        else:
            x = df_orig

        if not hasattr(model, "predict_proba"):
            return None
        return float(model.predict_proba(x)[0, 1])


_ensemble: MLKickerEnsemble | None = None


def get_ml_kicker_ensemble(*, reload: bool = False) -> MLKickerEnsemble:
    global _ensemble
    if reload or _ensemble is None:
        _ensemble = MLKickerEnsemble()
    return _ensemble


def blend_field_goal_projection(
    statistical_fgs: float,
    kicker_data: dict,
    team_data: dict,
    weather_data: dict | None = None,
    game_context: dict | None = None,
    weight_ml: float | None = None,
) -> tuple[float, dict]:
    """
    Blend statistical FG count with ML make probability at typical attempt distance.

    Returns (projected_fgs, metadata).
    """
    if weight_ml is None:
        weight_ml = float(os.getenv("NFL_KICKER_ML_BLEND_WEIGHT", "0.35"))

    ensemble = get_ml_kicker_ensemble()
    meta: dict = {"ml_used": False, "model_source": ensemble.model_source}
    if not ensemble.available or weight_ml <= 0:
        return statistical_fgs, meta

    ctx = dict(game_context or {})
    ctx.setdefault("kick_distance", 38.0)
    prob = ensemble.predict_success_probability(
        kicker_data, team_data, weather_data, ctx
    )
    if prob is None:
        return statistical_fgs, meta

    ml_fgs = 1.2 + prob * 2.3
    blended = (1.0 - weight_ml) * statistical_fgs + weight_ml * ml_fgs
    meta = {
        "ml_used": True,
        "model_source": ensemble.model_source,
        "ml_success_probability": round(prob, 3),
        "ml_projected_fgs": round(ml_fgs, 2),
        "statistical_fgs": round(statistical_fgs, 2),
        "blend_weight": weight_ml,
    }
    return round(blended, 2), meta
