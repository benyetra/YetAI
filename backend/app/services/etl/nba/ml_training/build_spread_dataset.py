"""Build (features, margin) dataset for NBA spread ML training."""

from __future__ import annotations

import bisect
import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import NBAGameLines, NBASpreadActuals
from app.services.etl.nba._spread_features import (
    SPREAD_MODEL_FEATURES,
    compute_game_features,
)

logger = logging.getLogger(__name__)


def build_from_rows(
    actuals: list, lines: dict[tuple, object], season_start: date, season_end: date
) -> tuple[pd.DataFrame, pd.Series]:
    """actuals: every stored game in date order (earlier seasons seed Elo/form).
    lines: (game_date, home, away) -> NBAGameLines row."""
    dates = [a.game_date for a in actuals]
    rows_features: list[dict] = []
    rows_target: list[float] = []
    for actual in actuals:
        if not (season_start <= actual.game_date <= season_end):
            continue
        prior = actuals[: bisect.bisect_left(dates, actual.game_date)]
        line = lines.get(
            (actual.game_date, actual.home_team_name, actual.away_team_name)
        )
        rows_features.append(
            compute_game_features(
                prior,
                game_date=actual.game_date,
                home_team_name=actual.home_team_name,
                away_team_name=actual.away_team_name,
                market_spread_home=line.spread_home if line else None,
                market_total=line.total if line else None,
            )
        )
        rows_target.append(float(actual.actual_margin))
    features = pd.DataFrame(rows_features, columns=SPREAD_MODEL_FEATURES)
    return features, pd.Series(rows_target, name="margin")


def build(season_start: date, season_end: date) -> tuple[pd.DataFrame, pd.Series]:
    db = SessionLocal()
    try:
        actuals = (
            db.query(NBASpreadActuals)
            .filter(NBASpreadActuals.game_date <= season_end)
            .order_by(NBASpreadActuals.game_date.asc())
            .all()
        )
        lines = {
            (g.game_date, g.home_team_name, g.away_team_name): g
            for g in db.query(NBAGameLines)
            .filter(NBAGameLines.game_date >= season_start)
            .filter(NBAGameLines.game_date <= season_end)
            .all()
        }
    finally:
        db.close()

    features, target = build_from_rows(actuals, lines, season_start, season_end)
    logger.info(
        "build_spread_dataset: %d games (%d with a market line)",
        len(features),
        int(features["market_spread_home"].notna().sum()),
    )
    return features, target
