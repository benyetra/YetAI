"""Assemble (features, target) DataFrame for prop model training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.core.database import SessionLocal
from app.services.ml.config import LeagueMLConfig

logger = logging.getLogger(__name__)


def build(
    config: LeagueMLConfig,
    stat_col: str,
    season_start: date,
    season_end: date,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (features_df, target_series) for training/validation."""
    if stat_col not in config.supported_stats:
        raise ValueError(
            f"stat {stat_col!r} not in supported_stats {config.supported_stats}"
        )

    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    model = config.recent_games_model
    try:
        all_rows = (
            db.query(model)
            .filter(model.game_date >= season_start)
            .filter(model.game_date <= season_end)
            .order_by(model.game_date.asc())
            .all()
        )
        logger.info(
            "build_training_dataset[%s]: %d candidate rows in window",
            config.table_prefix,
            len(all_rows),
        )
        for row in all_rows:
            target_value = getattr(row, stat_col)
            if target_value is None:
                continue
            feats = config.feature_builder(
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
