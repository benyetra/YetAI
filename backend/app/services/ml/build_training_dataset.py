"""Assemble (features, target) DataFrame for prop model training."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal
from app.services.ml.config import LeagueMLConfig

logger = logging.getLogger(__name__)

# Features take several queries per row, so a two-season build runs for hours.
# End the read transaction every RELEASE_EVERY rows so the connection goes back
# to the (pre-pinged) pool instead of one transaction held open for the whole
# build, which the server eventually drops.
RELEASE_EVERY = 500


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
        candidates = [
            (r.player_id, r.game_date, r.opponent_team_id, getattr(r, stat_col))
            for r in db.query(model)
            .filter(model.game_date >= season_start)
            .filter(model.game_date <= season_end)
            .order_by(model.game_date.asc())
            .all()
        ]
        db.rollback()
        logger.info(
            "build_training_dataset[%s]: %d candidate rows in window",
            config.table_prefix,
            len(candidates),
        )
        for i, (player_id, game_date, opponent_team_id, target_value) in enumerate(
            candidates, 1
        ):
            if target_value is None:
                continue
            kwargs = dict(
                stat_col=stat_col,
                player_id=player_id,
                game_date=game_date,
                opponent_team_id=opponent_team_id,
            )
            try:
                feats = config.feature_builder(db, **kwargs)
            except OperationalError:
                logger.warning(
                    "build_training_dataset[%s]: connection lost at row %d; "
                    "reconnecting",
                    config.table_prefix,
                    i,
                )
                db.close()
                db = SessionLocal()
                feats = config.feature_builder(db, **kwargs)
            if i % RELEASE_EVERY == 0:
                db.rollback()
                logger.info(
                    "build_training_dataset[%s]: %d/%d rows",
                    config.table_prefix,
                    i,
                    len(candidates),
                )
            if feats is None:
                continue
            rows_features.append(feats)
            rows_target.append(float(target_value))
        return pd.DataFrame(rows_features), pd.Series(rows_target, name=stat_col)
    finally:
        db.close()
