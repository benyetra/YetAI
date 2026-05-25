"""Build (features, actual_saves) dataset for NHL goalie ML training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import NHLGoalieActuals, NHLGoaliePredictions
from app.services.etl.nhl.goalie_saves_ml import (
    build_features_from_prediction,
    feature_names,
)

logger = logging.getLogger(__name__)


def _prediction_feature_dict(pred: NHLGoaliePredictions) -> dict:
    """Reconstruct heuristic inputs from stored prediction columns."""
    return {
        "predicted_saves": pred.predicted_saves,
        "predicted_shots_against": pred.predicted_shots_against,
        "predicted_save_pct": pred.predicted_save_pct,
        "goalie_recent_sv_pct": pred.goalie_recent_save_pct,
        "goalie_season_sv_pct": pred.goalie_season_save_pct,
        "opponent_shots_avg": pred.opponent_shots_avg,
        "is_home": pred.is_home,
        "saves_line": pred.saves_line,
    }


def build(season_start: date, season_end: date) -> tuple[pd.DataFrame, pd.Series]:
    """
    Join ``pred_nhl_goalie_predictions`` to ``pred_nhl_goalie_actuals`` on
    (goalie_id, game_date). Target is ``actual_saves``.
    """
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        actuals = (
            db.query(NHLGoalieActuals)
            .filter(NHLGoalieActuals.game_date >= season_start)
            .filter(NHLGoalieActuals.game_date <= season_end)
            .order_by(NHLGoalieActuals.game_date.asc())
            .all()
        )
        for actual in actuals:
            pred = (
                db.query(NHLGoaliePredictions)
                .filter(
                    NHLGoaliePredictions.goalie_id == actual.goalie_id,
                    NHLGoaliePredictions.game_date == actual.game_date,
                )
                .first()
            )
            if pred is None:
                continue

            feat_src = _prediction_feature_dict(pred)
            fu = pred.features_used if isinstance(pred.features_used, dict) else {}
            if fu.get("heuristic_saves") is not None:
                feat_src["predicted_saves"] = fu["heuristic_saves"]

            rows_features.append(build_features_from_prediction(feat_src))
            rows_target.append(float(actual.actual_saves))

        logger.info(
            "build_goalie_dataset: %d rows (of %d actuals)",
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
        return df, pd.Series(rows_target, name="actual_saves")
    finally:
        db.close()
