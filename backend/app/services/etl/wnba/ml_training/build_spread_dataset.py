"""Build (features, margin) dataset for WNBA spread ML training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import WNBAGameLines, WNBASpreadActuals
from app.services.etl.wnba._spread_features import build_game_features

logger = logging.getLogger(__name__)


def build(season_start: date, season_end: date) -> tuple[pd.DataFrame, pd.Series]:
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        actuals = (
            db.query(WNBASpreadActuals)
            .filter(WNBASpreadActuals.game_date >= season_start)
            .filter(WNBASpreadActuals.game_date <= season_end)
            .order_by(WNBASpreadActuals.game_date.asc())
            .all()
        )
        for actual in actuals:
            line = (
                db.query(WNBAGameLines)
                .filter(
                    WNBAGameLines.game_date == actual.game_date,
                    WNBAGameLines.home_team_name == actual.home_team_name,
                    WNBAGameLines.away_team_name == actual.away_team_name,
                )
                .first()
            )
            feats = build_game_features(
                db,
                game_date=actual.game_date,
                home_team_name=actual.home_team_name,
                away_team_name=actual.away_team_name,
                home_team_id=None,
                away_team_id=None,
                market_spread_home=line.spread_home if line else None,
                market_total=line.total if line else None,
                spread_actuals_model=WNBASpreadActuals,
            )
            if feats is None:
                continue
            rows_features.append(feats)
            rows_target.append(float(actual.actual_margin))
        logger.info(
            "build_spread_dataset: %d games with features (of %d actuals)",
            len(rows_features),
            len(actuals),
        )
        return pd.DataFrame(rows_features), pd.Series(rows_target, name="margin")
    finally:
        db.close()
