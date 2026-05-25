"""Build (features, residual) dataset for NBA totals ML training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import NBATotalsActuals, NBATotalsProjections
from app.services.etl.nba.totals_ml import features_from_projection

logger = logging.getLogger(__name__)


def build(season_start: date, season_end: date) -> tuple[pd.DataFrame, pd.Series]:
    """
    Target = actual_total - heuristic_total (residual on rule-based baseline).

    Heuristic is taken from projection.factors.ml_shadow when present, else
    projected_total on the stored row.
    """
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        actuals = (
            db.query(NBATotalsActuals)
            .filter(NBATotalsActuals.game_date >= season_start)
            .filter(NBATotalsActuals.game_date <= season_end)
            .order_by(NBATotalsActuals.game_date.asc())
            .all()
        )
        for actual in actuals:
            proj = (
                db.query(NBATotalsProjections)
                .filter(
                    NBATotalsProjections.game_date == actual.game_date,
                    NBATotalsProjections.home_team_name == actual.home_team_name,
                    NBATotalsProjections.away_team_name == actual.away_team_name,
                )
                .first()
            )
            if proj is None:
                continue

            shadow = (proj.factors or {}).get("ml_shadow") if proj.factors else {}
            heuristic = None
            if isinstance(shadow, dict):
                heuristic = shadow.get("heuristic_total")
            if heuristic is None:
                heuristic = proj.projected_total
            if heuristic is None:
                continue

            proj_dict = {
                "projected_total": heuristic,
                "heuristic_total": heuristic,
                "base_projection": proj.base_projection,
                "expected_pace": proj.expected_pace,
                "home_offensive_rating": proj.home_offensive_rating,
                "away_offensive_rating": proj.away_offensive_rating,
                "home_defensive_rating": proj.home_defensive_rating,
                "away_defensive_rating": proj.away_defensive_rating,
                "injury_adjustment": proj.injury_adjustment,
                "rest_adjustment": proj.rest_adjustment,
                "venue_adjustment": proj.venue_adjustment,
                "form_adjustment": proj.form_adjustment,
                "total_adjustment": proj.total_adjustment,
                "market_total": proj.market_total,
            }
            rows_features.append(features_from_projection(proj_dict))
            rows_target.append(float(actual.actual_total) - float(heuristic))

        logger.info(
            "build_totals_dataset: %d rows (of %d actuals)",
            len(rows_features),
            len(actuals),
        )
        return pd.DataFrame(rows_features), pd.Series(rows_target, name="residual")
    finally:
        db.close()
