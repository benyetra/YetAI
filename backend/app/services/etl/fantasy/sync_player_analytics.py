"""
Backfill ``player_analytics`` from nflverse weekly data.

Maps nflverse ``player_id`` (GSIS) → Sleeper ID → ``fantasy_players.id`` and upserts
weekly fantasy scoring rows used by start/sit and trade analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.fantasy_models import FantasyPlatform, FantasyPlayer, PlayerAnalytics
from app.services.fantasy_sleeper_unified import fantasy_sleeper_unified

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compute_ppr_points(row: pd.Series) -> float:
    for column in ("fantasy_points_ppr", "fantasy_points"):
        val = _safe_float(row.get(column))
        if val is not None:
            return val

    passing_yds = _safe_float(row.get("passing_yards")) or 0.0
    passing_tds = _safe_float(row.get("passing_tds")) or 0.0
    interceptions = _safe_float(row.get("interceptions")) or 0.0
    rushing_yds = _safe_float(row.get("rushing_yards")) or 0.0
    rushing_tds = _safe_float(row.get("rushing_tds")) or 0.0
    receptions = _safe_float(row.get("receptions")) or 0.0
    receiving_yds = _safe_float(row.get("receiving_yards")) or 0.0
    receiving_tds = _safe_float(row.get("receiving_tds")) or 0.0
    fumbles_lost = _safe_float(row.get("rushing_fumbles_lost")) or 0.0
    fumbles_lost += _safe_float(row.get("receiving_fumbles_lost")) or 0.0

    return (
        passing_yds * 0.04
        + passing_tds * 4
        - interceptions * 2
        + rushing_yds * 0.1
        + rushing_tds * 6
        + receptions
        + receiving_yds * 0.1
        + receiving_tds * 6
        - fumbles_lost * 2
    )


async def _build_gsis_to_fantasy_player_map(db: Session) -> Dict[str, int]:
    """Map GSIS IDs to ``fantasy_players.id`` via Sleeper metadata."""
    sleeper_players = await fantasy_sleeper_unified.sleeper._get_all_players()
    sleeper_to_gsis: Dict[str, str] = {}
    for sleeper_id, pdata in sleeper_players.items():
        gsis_id = pdata.get("gsis_id")
        if gsis_id:
            sleeper_to_gsis[str(sleeper_id)] = str(gsis_id)

    fantasy_rows = (
        db.query(FantasyPlayer.id, FantasyPlayer.platform_player_id)
        .filter(FantasyPlayer.platform == FantasyPlatform.SLEEPER)
        .all()
    )
    gsis_to_fantasy: Dict[str, int] = {}
    for fantasy_id, sleeper_id in fantasy_rows:
        gsis_id = sleeper_to_gsis.get(str(sleeper_id))
        if gsis_id:
            gsis_to_fantasy[gsis_id] = fantasy_id
    return gsis_to_fantasy


def _load_weekly_frame(season: int) -> pd.DataFrame:
    try:
        import nfl_data_py as nfl
    except ImportError as exc:
        raise ImportError(
            "nfl_data_py is required for player_analytics ETL. "
            "Install with: pip install nfl-data-py==0.3.3 --no-deps && pip install appdirs fastparquet"
        ) from exc

    weekly = nfl.import_weekly_data([season])
    if weekly is None or weekly.empty:
        return pd.DataFrame()
    weekly = weekly.copy()
    weekly["player_id"] = weekly["player_id"].astype(str)
    return weekly


async def sync_player_analytics(
    db: Session,
    *,
    season: Optional[int] = None,
    max_week: Optional[int] = None,
) -> Dict[str, Any]:
    """Upsert weekly analytics rows for the given season."""
    season = season or datetime.now().year
    await fantasy_sleeper_unified.sync_fantasy_players(db)
    gsis_to_fantasy = await _build_gsis_to_fantasy_player_map(db)

    weekly = _load_weekly_frame(season)
    if weekly.empty:
        return {
            "season": season,
            "rows_upserted": 0,
            "rows_skipped": 0,
            "message": f"No nflverse weekly data for season {season}",
        }

    if max_week is not None:
        weekly = weekly[weekly["week"] <= max_week]

    upserted = 0
    skipped = 0

    for _, row in weekly.iterrows():
        gsis_id = str(row.get("player_id", ""))
        fantasy_player_id = gsis_to_fantasy.get(gsis_id)
        if fantasy_player_id is None:
            skipped += 1
            continue

        week = _safe_int(row.get("week"))
        if week is None:
            skipped += 1
            continue

        ppr_points = _compute_ppr_points(row)
        targets = _safe_int(row.get("targets")) or 0
        carries = _safe_int(row.get("carries")) or 0
        receptions = _safe_int(row.get("receptions")) or 0
        receiving_yards = _safe_int(row.get("receiving_yards")) or 0
        rushing_yards = _safe_int(row.get("rushing_yards")) or 0

        existing = (
            db.query(PlayerAnalytics)
            .filter(
                PlayerAnalytics.player_id == fantasy_player_id,
                PlayerAnalytics.week == week,
                PlayerAnalytics.season == season,
            )
            .first()
        )

        payload = {
            "ppr_points": ppr_points,
            "half_ppr_points": ppr_points - (receptions * 0.5),
            "standard_points": ppr_points - receptions,
            "targets": targets,
            "carries": carries,
            "receptions": receptions,
            "receiving_yards": receiving_yards,
            "rushing_yards": rushing_yards,
            "opponent": row.get("opponent_team"),
            "target_share": _safe_float(row.get("target_share")),
            "snap_percentage": _safe_float(row.get("offense_pct")),
            "points_per_target": (ppr_points / targets if targets > 0 else None),
        }

        if existing is None:
            db.add(
                PlayerAnalytics(
                    player_id=fantasy_player_id,
                    week=week,
                    season=season,
                    **payload,
                )
            )
        else:
            for key, value in payload.items():
                setattr(existing, key, value)

        upserted += 1

    db.commit()
    logger.info(
        "player_analytics sync season=%s upserted=%s skipped=%s",
        season,
        upserted,
        skipped,
    )
    return {
        "season": season,
        "rows_upserted": upserted,
        "rows_skipped": skipped,
        "fantasy_players_mapped": len(gsis_to_fantasy),
        "message": f"Upserted {upserted} player_analytics rows for {season}",
    }


def run(
    *, season: Optional[int] = None, max_week: Optional[int] = None
) -> Dict[str, Any]:
    """Synchronous entrypoint for Celery tasks."""
    import asyncio

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(sync_player_analytics(db, season=season, max_week=max_week))
    finally:
        db.close()
