"""
Backfill ``player_analytics`` from nflverse weekly data.

Maps nflverse ``player_id`` (GSIS) → Sleeper ID → ``fantasy_players.id`` and upserts
weekly fantasy scoring rows used by start/sit and trade analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.models.fantasy_models import FantasyPlatform, FantasyPlayer, PlayerAnalytics
from app.services.fantasy_sleeper_unified import fantasy_sleeper_unified

logger = logging.getLogger(__name__)

_ANALYTICS_COMPARE_KEYS = (
    "ppr_points",
    "half_ppr_points",
    "standard_points",
    "targets",
    "carries",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "opponent",
    "target_share",
    "snap_percentage",
    "points_per_target",
)


def _values_equal(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left) - float(right)) < 1e-6
        except (TypeError, ValueError):
            return False
    return left == right


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


def _load_nflverse_sleeper_to_gsis() -> Dict[str, str]:
    """Map Sleeper IDs to GSIS via nflverse ``import_ids`` crosswalk."""
    try:
        import nfl_data_py as nfl
    except ImportError:
        return {}

    try:
        ids_df = nfl.import_ids()
    except Exception as exc:
        logger.warning("nflverse import_ids unavailable: %s", exc)
        return {}

    if ids_df is None or ids_df.empty:
        return {}

    mapping: Dict[str, str] = {}
    for _, row in ids_df.iterrows():
        gsis_id = row.get("gsis_id")
        sleeper_id = row.get("sleeper_id")
        if gsis_id is None or sleeper_id is None:
            continue
        if isinstance(gsis_id, float) and pd.isna(gsis_id):
            continue
        if isinstance(sleeper_id, float) and pd.isna(sleeper_id):
            continue
        gsis_str = str(gsis_id).strip()
        sleeper_str = str(int(float(sleeper_id)))
        if gsis_str and sleeper_str:
            mapping[sleeper_str] = gsis_str
    return mapping


async def _build_gsis_to_fantasy_player_map(db: Session) -> Dict[str, int]:
    """Map GSIS IDs to ``fantasy_players.id`` via Sleeper + nflverse metadata."""
    sleeper_players = await fantasy_sleeper_unified.sleeper._get_all_players()
    sleeper_to_gsis: Dict[str, str] = {}
    for sleeper_id, pdata in sleeper_players.items():
        gsis_id = pdata.get("gsis_id")
        if gsis_id:
            sleeper_to_gsis[str(sleeper_id)] = str(gsis_id)

    # Sleeper omits gsis_id for many active players (e.g. Jahmyr Gibbs / 9221).
    nflverse_sleeper_to_gsis = _load_nflverse_sleeper_to_gsis()
    for sleeper_id, gsis_id in nflverse_sleeper_to_gsis.items():
        sleeper_to_gsis.setdefault(sleeper_id, gsis_id)

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


def _normalize_weekly_frame(weekly: pd.DataFrame) -> pd.DataFrame:
    """Align nflverse schema differences across releases."""
    weekly = weekly.copy()
    if (
        "passing_interceptions" in weekly.columns
        and "interceptions" not in weekly.columns
    ):
        weekly["interceptions"] = weekly["passing_interceptions"]
    if "team" in weekly.columns and "recent_team" not in weekly.columns:
        weekly["recent_team"] = weekly["team"]
    weekly["player_id"] = weekly["player_id"].astype(str)
    return weekly


def _is_remote_not_found(exc: BaseException) -> bool:
    from urllib.error import HTTPError

    if isinstance(exc, HTTPError) and exc.code == 404:
        return True
    cause = getattr(exc, "__cause__", None)
    return isinstance(cause, HTTPError) and cause.code == 404


def _load_weekly_frame(season: int) -> pd.DataFrame:
    try:
        import nfl_data_py as nfl
    except ImportError as exc:
        raise ImportError(
            "nfl_data_py is required for player_analytics ETL. "
            "Install with: cd backend && .venv/bin/pip install nfl-data-py==0.3.3 --no-deps && .venv/bin/pip install appdirs fastparquet"
        ) from exc

    try:
        weekly = nfl.import_weekly_data([season])
        if weekly is not None and not weekly.empty:
            return _normalize_weekly_frame(weekly)
    except Exception as exc:
        if not _is_remote_not_found(exc):
            raise
        logger.warning(
            "nfl_data_py player_stats_%s.parquet unavailable (%s); "
            "trying stats_player_week release",
            season,
            exc,
        )

    # nflverse moved weekly player stats to stats_player releases (2025+).
    stats_player_url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"stats_player/stats_player_week_{season}.parquet"
    )
    try:
        weekly = pd.read_parquet(stats_player_url)
    except Exception as exc:
        if _is_remote_not_found(exc):
            logger.warning("No nflverse weekly data for season %s", season)
            return pd.DataFrame()
        raise

    if weekly is None or weekly.empty:
        return pd.DataFrame()
    return _normalize_weekly_frame(weekly)


def _load_existing_rows(
    db: Session, season: int
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """Map (player_id, week) → existing row snapshot for one season."""
    rows = (
        db.query(
            PlayerAnalytics.id,
            PlayerAnalytics.player_id,
            PlayerAnalytics.week,
            PlayerAnalytics.ppr_points,
            PlayerAnalytics.half_ppr_points,
            PlayerAnalytics.standard_points,
            PlayerAnalytics.targets,
            PlayerAnalytics.carries,
            PlayerAnalytics.receptions,
            PlayerAnalytics.receiving_yards,
            PlayerAnalytics.rushing_yards,
            PlayerAnalytics.opponent,
            PlayerAnalytics.target_share,
            PlayerAnalytics.snap_percentage,
            PlayerAnalytics.points_per_target,
        )
        .filter(PlayerAnalytics.season == season)
        .order_by(PlayerAnalytics.id)
        .all()
    )
    existing: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for row in rows:
        key = (row.player_id, row.week)
        if key in existing:
            continue
        existing[key] = {
            "id": row.id,
            **{field: getattr(row, field) for field in _ANALYTICS_COMPARE_KEYS},
        }
    return existing


def _analytics_payload_changed(
    existing: Dict[str, Any], payload: Dict[str, Any]
) -> bool:
    return any(
        not _values_equal(existing.get(key), payload.get(key))
        for key in _ANALYTICS_COMPARE_KEYS
    )


def _row_payload(
    *,
    row: pd.Series,
    fantasy_player_id: int,
    week: int,
    season: int,
) -> Dict[str, Any]:
    ppr_points = _compute_ppr_points(row)
    targets = _safe_int(row.get("targets")) or 0
    carries = _safe_int(row.get("carries")) or 0
    receptions = _safe_int(row.get("receptions")) or 0
    receiving_yards = _safe_int(row.get("receiving_yards")) or 0
    rushing_yards = _safe_int(row.get("rushing_yards")) or 0
    return {
        "player_id": fantasy_player_id,
        "week": week,
        "season": season,
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


async def sync_player_analytics(
    db: Session,
    *,
    season: Optional[int] = None,
    max_week: Optional[int] = None,
    sync_fantasy_players: bool = False,
) -> Dict[str, Any]:
    """Upsert weekly analytics rows for the given season."""
    season = season or datetime.now().year
    player_sync_result: Optional[Dict[str, Any]] = None
    if sync_fantasy_players:
        player_sync_result = await fantasy_sleeper_unified.sync_fantasy_players(db)
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

    existing_rows = _load_existing_rows(db, season)
    to_insert: List[Dict[str, Any]] = []
    to_update: List[Dict[str, Any]] = []
    upserted = 0
    skipped = 0
    unchanged = 0
    now = datetime.utcnow()

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

        payload = _row_payload(
            row=row,
            fantasy_player_id=fantasy_player_id,
            week=week,
            season=season,
        )
        existing = existing_rows.get((fantasy_player_id, week))
        if existing is None:
            to_insert.append({**payload, "created_at": now})
            upserted += 1
        elif _analytics_payload_changed(existing, payload):
            to_update.append({"id": existing["id"], **payload})
            upserted += 1
        else:
            unchanged += 1

    if to_insert:
        db.bulk_insert_mappings(PlayerAnalytics, to_insert)
    if to_update:
        db.bulk_update_mappings(PlayerAnalytics, to_update)

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
        "rows_unchanged": unchanged,
        "rows_skipped": skipped,
        "fantasy_players_mapped": len(gsis_to_fantasy),
        "fantasy_players_sync": player_sync_result,
        "message": f"Upserted {upserted} player_analytics rows for {season}",
    }


async def audit_player_analytics_mapping(
    db: Session,
    *,
    season: Optional[int] = None,
) -> Dict[str, Any]:
    """Report GSIS mapping coverage vs nflverse weekly rows (no DB writes)."""
    season = season or datetime.now().year
    gsis_to_fantasy = await _build_gsis_to_fantasy_player_map(db)
    sleeper_catalog = len(await fantasy_sleeper_unified.sleeper._get_all_players())
    db_players = (
        db.query(FantasyPlayer.id)
        .filter(FantasyPlayer.platform == FantasyPlatform.SLEEPER)
        .count()
    )
    analytics_rows = (
        db.query(PlayerAnalytics.id).filter(PlayerAnalytics.season == season).count()
    )

    weekly = _load_weekly_frame(season)
    total_weekly = len(weekly)
    mappable = 0
    skipped_unmapped = 0
    if not weekly.empty:
        for _, row in weekly.iterrows():
            gsis_id = str(row.get("player_id", ""))
            if gsis_to_fantasy.get(gsis_id) is None:
                skipped_unmapped += 1
            else:
                mappable += 1

    skip_rate_pct = (
        round(100.0 * skipped_unmapped / total_weekly, 1) if total_weekly else 0.0
    )
    return {
        "season": season,
        "fantasy_players_db": db_players,
        "sleeper_catalog_players": sleeper_catalog,
        "fantasy_players_mapped": len(gsis_to_fantasy),
        "player_analytics_rows": analytics_rows,
        "nflverse_weekly_rows": total_weekly,
        "rows_mappable": mappable,
        "rows_skipped_unmapped": skipped_unmapped,
        "skip_rate_pct": skip_rate_pct,
        "healthy": len(gsis_to_fantasy) >= 1000 and analytics_rows > 0,
    }


def run(
    *,
    season: Optional[int] = None,
    max_week: Optional[int] = None,
    sync_fantasy_players: bool = False,
) -> Dict[str, Any]:
    """Synchronous entrypoint for Celery tasks."""
    import asyncio

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(
            sync_player_analytics(
                db,
                season=season,
                max_week=max_week,
                sync_fantasy_players=sync_fantasy_players,
            )
        )
    finally:
        db.close()
