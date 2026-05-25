"""Build (features, residual) dataset for NHL team totals ML training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import NHLTeamTotalsActuals, NHLTeamTotalsPredictions
from app.services.etl.nhl.team_totals_ml import (
    build_features_from_prediction,
    feature_names,
    predict_total_heuristic,
)

logger = logging.getLogger(__name__)


def _prediction_feature_dict(pred: NHLTeamTotalsPredictions) -> dict:
    fu = pred.features_used if isinstance(pred.features_used, dict) else {}
    heuristic = fu.get("heuristic_total")
    if heuristic is None:
        heuristic = pred.predicted_total_goals
    return {
        "predicted_total_goals": heuristic,
        "heuristic_total": heuristic,
        "predicted_home_goals": pred.predicted_home_goals,
        "predicted_away_goals": pred.predicted_away_goals,
        "home_offense_rating": fu.get("home_offense_rating"),
        "away_offense_rating": fu.get("away_offense_rating"),
        "home_defense_rating": fu.get("home_defense_rating"),
        "away_defense_rating": fu.get("away_defense_rating"),
        "combined_pace": fu.get("combined_pace"),
        "home_pp_pct": fu.get("home_pp_pct"),
        "away_pp_pct": fu.get("away_pp_pct"),
        "home_pk_pct": fu.get("home_pk_pct"),
        "away_pk_pct": fu.get("away_pk_pct"),
        "suggested_ou_line": pred.suggested_ou_line,
        "draftkings_ou_line": pred.draftkings_ou_line,
    }


def build(season_start: date, season_end: date) -> tuple[pd.DataFrame, pd.Series]:
    """
    Join team totals predictions to actuals. Target is residual
    ``actual_total_goals - heuristic_total``.
    """
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        actuals = (
            db.query(NHLTeamTotalsActuals)
            .filter(NHLTeamTotalsActuals.game_date >= season_start)
            .filter(NHLTeamTotalsActuals.game_date <= season_end)
            .order_by(NHLTeamTotalsActuals.game_date.asc())
            .all()
        )
        for actual in actuals:
            pred = (
                db.query(NHLTeamTotalsPredictions)
                .filter(
                    NHLTeamTotalsPredictions.home_team_id == actual.home_team_id,
                    NHLTeamTotalsPredictions.away_team_id == actual.away_team_id,
                    NHLTeamTotalsPredictions.game_date == actual.game_date,
                )
                .first()
            )
            if pred is None:
                continue

            feat_src = _prediction_feature_dict(pred)
            feats = build_features_from_prediction(feat_src)
            heuristic = predict_total_heuristic(feats)
            actual_total = float(actual.actual_total_goals)
            rows_features.append(feats)
            rows_target.append(actual_total - heuristic)

        logger.info(
            "build_team_totals_dataset: %d rows (of %d actuals)",
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
        return df, pd.Series(rows_target, name="residual")
    finally:
        db.close()
