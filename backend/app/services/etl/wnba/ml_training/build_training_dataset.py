"""Assemble (features, target) DataFrame for WNBA prop model training.

Iterates pred_wnba_recent_games rows; for each row, computes the inference
feature vector using _feature_engineering.build_features (with the row's
game_date as the "target" date, ensuring no leakage of the row's own stats).
The row's actual stat value becomes the target.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._feature_engineering import build_features

logger = logging.getLogger(__name__)


def build(
    stat_col: str, season_start: date, season_end: date
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (features_df, target_series) for training/validation."""
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    try:
        all_rows = (
            db.query(WNBARecentGames)
            .filter(WNBARecentGames.game_date >= season_start)
            .filter(WNBARecentGames.game_date <= season_end)
            .order_by(WNBARecentGames.game_date.asc())
            .all()
        )
        logger.info(
            "build_training_dataset: %d candidate rows in window", len(all_rows)
        )
        for row in all_rows:
            target_value = getattr(row, stat_col)
            if target_value is None:
                continue
            feats = build_features(
                db,
                stat_col=stat_col,
                player_id=row.player_id,
                game_date=row.game_date,
                opponent_team_id=row.opponent_team_id,
            )
            if feats is None:
                continue
            rows_features.append(feats)
            rows_target.append(float(target_value))
        return pd.DataFrame(rows_features), pd.Series(rows_target, name=stat_col)
    finally:
        db.close()
