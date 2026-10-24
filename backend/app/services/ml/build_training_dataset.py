"""Assemble (features, target) DataFrame for prop model training."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal
from app.services.ml.config import LeagueMLConfig

logger = logging.getLogger(__name__)

# Features take several queries per row, so a two-season build is hours of
# round trips. End the read transaction every RELEASE_EVERY rows so the
# connection goes back to the (pre-pinged) pool instead of one transaction held
# open for the whole build, which the server eventually drops.
RELEASE_EVERY = 500
# Builds are I/O bound: split the rows into contiguous chunks and run them on
# separate sessions. Small builds (and tests) stay on one session.
PARALLEL_MIN_ROWS = 2000
WORKERS = 8
CHUNKS_PER_WORKER = 4


def _build_chunk(config: LeagueMLConfig, stat_col: str, rows: list, label: str):
    """(features, targets) for one contiguous run of candidate rows, in order."""
    db = SessionLocal()
    feats_out: list[dict] = []
    targets: list[float] = []
    try:
        for i, (player_id, game_date, opponent_team_id, target_value) in enumerate(
            rows, 1
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
                    "build_training_dataset[%s]: connection lost at row %d of %s; "
                    "reconnecting",
                    config.table_prefix,
                    i,
                    label,
                )
                db.close()
                db = SessionLocal()
                feats = config.feature_builder(db, **kwargs)
            if i % RELEASE_EVERY == 0:
                db.rollback()
                logger.info(
                    "build_training_dataset[%s]: %s %d/%d rows",
                    config.table_prefix,
                    label,
                    i,
                    len(rows),
                )
            if feats is None:
                continue
            feats_out.append(feats)
            targets.append(float(target_value))
        return feats_out, targets
    finally:
        db.close()


def build(
    config: LeagueMLConfig,
    stat_col: str,
    season_start: date,
    season_end: date,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (features_df, target_series) for training/validation.

    Rows come back in game-date order whatever the parallelism."""
    if stat_col not in config.supported_stats:
        raise ValueError(
            f"stat {stat_col!r} not in supported_stats {config.supported_stats}"
        )

    model = config.recent_games_model
    db = SessionLocal()
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
    finally:
        db.close()
    logger.info(
        "build_training_dataset[%s]: %d candidate rows in window",
        config.table_prefix,
        len(candidates),
    )

    if len(candidates) < PARALLEL_MIN_ROWS:
        chunks = [candidates]
    else:
        n = WORKERS * CHUNKS_PER_WORKER
        size = -(-len(candidates) // n)
        chunks = [candidates[i : i + size] for i in range(0, len(candidates), size)]

    if len(chunks) == 1:
        results = [_build_chunk(config, stat_col, chunks[0], "chunk 1/1")]
    else:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(
                pool.map(
                    lambda ic: _build_chunk(
                        config, stat_col, ic[1], f"chunk {ic[0] + 1}/{len(chunks)}"
                    ),
                    enumerate(chunks),
                )
            )
    rows_features = [f for feats, _ in results for f in feats]
    rows_target = [t for _, targets in results for t in targets]
    return pd.DataFrame(rows_features), pd.Series(rows_target, name=stat_col)
