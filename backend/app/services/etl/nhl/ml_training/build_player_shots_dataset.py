"""Build (features, actual_shots) dataset for NHL player SOG ML training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
)
from app.services.etl.nhl.player_shots_ml import (
    build_features_from_prediction,
    feature_names,
)

logger = logging.getLogger(__name__)


def _prediction_feature_dict(pred: NHLPlayerShotsPredictions) -> dict:
    """Reconstruct heuristic inputs from stored prediction + adjustment metadata."""
    fu = pred.features_used if isinstance(pred.features_used, dict) else {}
    base = {
        "predicted_shots": pred.predicted_shots,
        "baseline_shots": fu.get("baseline_shots"),
        "ice_time_adjustment": fu.get("ice_time_adjustment", 1.0),
        "opponent_shots_adjustment": fu.get("opponent_shots_adjustment", 1.0),
        "blocks_adjustment": fu.get("blocks_adjustment", 1.0),
        "position_adjustment": fu.get("position_adjustment", 1.0),
        "home_ice_adjustment": fu.get("home_ice_adjustment", 1.0),
        "player_toi_per_game": fu.get("player_toi_per_game"),
        "opponent_shots_against_pg": fu.get("opponent_shots_against_pg"),
        "opponent_blocks_pg": fu.get("opponent_blocks_pg"),
        "player_position": fu.get("player_position"),
        "is_home": fu.get("is_home"),
        "shots_line": pred.shots_line,
    }
    if fu.get("heuristic_shots") is not None:
        base["predicted_shots"] = fu["heuristic_shots"]
    return base


def build(season_start: date, season_end: date) -> tuple[pd.DataFrame, pd.Series]:
    """
    Join ``pred_nhl_player_shots_predictions`` to ``pred_nhl_player_shots_actuals``
    on (player_id, game_date). Target is ``actual_shots``.
    """
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        actuals = (
            db.query(NHLPlayerShotsActuals)
            .filter(NHLPlayerShotsActuals.game_date >= season_start)
            .filter(NHLPlayerShotsActuals.game_date <= season_end)
            .order_by(NHLPlayerShotsActuals.game_date.asc())
            .all()
        )
        for actual in actuals:
            pred = (
                db.query(NHLPlayerShotsPredictions)
                .filter(
                    NHLPlayerShotsPredictions.player_id == actual.player_id,
                    NHLPlayerShotsPredictions.game_date == actual.game_date,
                )
                .first()
            )
            if pred is None:
                continue

            rows_features.append(
                build_features_from_prediction(_prediction_feature_dict(pred))
            )
            rows_target.append(float(actual.actual_shots))

        logger.info(
            "build_player_shots_dataset: %d rows (of %d actuals)",
            len(rows_features),
            len(actuals),
        )
        df = pd.DataFrame(rows_features)
        if not df.empty:
            order = feature_names()
            for col in order:
                if col not in df.columns:
                    df[col] = 0.0
            df = df[order]
        return df, pd.Series(rows_target, name="actual_shots")
    finally:
        db.close()
