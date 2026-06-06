"""WNBA training dataset builder — preloads context to avoid N+1 DB queries."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._feature_engineering import build_features
from app.services.etl.wnba._training_context import load_training_context

logger = logging.getLogger(__name__)

PROGRESS_EVERY = 2000


def build(
    stat_col: str, season_start: date, season_end: date
) -> tuple[pd.DataFrame, pd.Series]:
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        ctx = load_training_context(db, season_start, season_end)
        all_rows = (
            db.query(WNBARecentGames)
            .filter(WNBARecentGames.game_date >= season_start)
            .filter(WNBARecentGames.game_date <= season_end)
            .order_by(WNBARecentGames.game_date.asc())
            .all()
        )
        logger.info(
            "build_training_dataset[wnba]: %d candidate rows in window",
            len(all_rows),
        )
        for i, row in enumerate(all_rows, start=1):
            target_value = getattr(row, stat_col)
            if target_value is None:
                continue
            feats = build_features(
                db,
                stat_col=stat_col,
                player_id=row.player_id,
                game_date=row.game_date,
                opponent_team_id=row.opponent_team_id,
                ctx=ctx,
            )
            if feats is None:
                continue
            rows_features.append(feats)
            rows_target.append(float(target_value))
            if i % PROGRESS_EVERY == 0:
                logger.info(
                    "build_training_dataset[wnba]: %d/%d candidates, %d feature rows",
                    i,
                    len(all_rows),
                    len(rows_features),
                )
        logger.info(
            "build_training_dataset[wnba]: finished %d feature rows from %d candidates",
            len(rows_features),
            len(all_rows),
        )
        return pd.DataFrame(rows_features), pd.Series(rows_target, name=stat_col)
    finally:
        db.close()
