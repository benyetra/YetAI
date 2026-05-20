"""
Optional NFL kicker FG ensemble (.pkl models shipped under backend/models/nfl/).

Blends ML success probability into projected field goals when models are present.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import joblib

from app.services.etl.nfl.ml_feature_mapping import get_feature_mapper

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).resolve().parents[4] / "models" / "nfl"
_MODEL_FILES = {
    "logistic": "logistic_model.pkl",
    "random_forest": "random_forest_model.pkl",
    "gradient_boosting": "gradient_boosting_model.pkl",
    "xgboost": "xgboost_model.pkl",
}


class MLKickerEnsemble:
    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.scalers: dict[str, Any] = {}
        self.feature_mapper = get_feature_mapper()
        self._load()

    def _load(self) -> None:
        for name, filename in _MODEL_FILES.items():
            path = _MODEL_DIR / filename
            if path.exists():
                self.models[name] = joblib.load(path)
                logger.info("Loaded NFL kicker model %s", name)
        scaler_path = _MODEL_DIR / "main_scaler.pkl"
        if scaler_path.exists():
            self.scalers["main"] = joblib.load(scaler_path)

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


def get_ml_kicker_ensemble() -> MLKickerEnsemble:
    global _ensemble
    if _ensemble is None:
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
    meta: dict = {"ml_used": False}
    if not ensemble.available or weight_ml <= 0:
        return statistical_fgs, meta

    ctx = dict(game_context or {})
    ctx.setdefault("kick_distance", 38.0)
    prob = ensemble.predict_success_probability(
        kicker_data, team_data, weather_data, ctx
    )
    if prob is None:
        return statistical_fgs, meta

    # Map success probability to expected FGs (1.5–3.5 typical range)
    ml_fgs = 1.2 + prob * 2.3
    blended = (1.0 - weight_ml) * statistical_fgs + weight_ml * ml_fgs
    meta = {
        "ml_used": True,
        "ml_success_probability": round(prob, 3),
        "ml_projected_fgs": round(ml_fgs, 2),
        "statistical_fgs": round(statistical_fgs, 2),
        "blend_weight": weight_ml,
    }
    return round(blended, 2), meta
