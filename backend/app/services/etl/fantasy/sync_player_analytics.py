"""
Backfill ``player_analytics`` from nflverse weekly data.

Maps nflverse ``player_id`` (GSIS) → Sleeper ID → ``fantasy_players.id`` and upserts
weekly fantasy scoring rows used by start/sit and trade analytics.
"""

from __future__ import annotations

import logging
import statistics
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
    "offensive_snaps",
    "points_per_target",
    "points_per_snap",
    "red_zone_targets",
    "red_zone_carries",
    "red_zone_touches",
    "red_zone_share",
    "game_script",
    "injury_designation",
    "boom_rate",
    "bust_rate",
    "floor_score",
    "ceiling_score",
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


def _normalize_snap_percentage(value: Any) -> Optional[float]:
    """Store snap share on 0-100 scale for UI; nflverse uses 0-1 fractions."""
    snap = _safe_float(value)
    if snap is None:
        return None
    if snap <= 1.0:
        return snap * 100.0
    return snap


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


def _load_pfr_to_gsis_map() -> Dict[str, str]:
    """Map PFR player IDs to GSIS via nflverse ``import_ids`` crosswalk."""
    try:
        import nfl_data_py as nfl
    except ImportError:
        return {}

    try:
        ids_df = nfl.import_ids()
    except Exception as exc:
        logger.warning("nflverse import_ids unavailable for snap merge: %s", exc)
        return {}

    if ids_df is None or ids_df.empty or "pfr_id" not in ids_df.columns:
        return {}

    mapping: Dict[str, str] = {}
    for _, row in ids_df.iterrows():
        pfr_id = row.get("pfr_id")
        gsis_id = row.get("gsis_id")
        if pfr_id is None or gsis_id is None:
            continue
        if isinstance(pfr_id, float) and pd.isna(pfr_id):
            continue
        if isinstance(gsis_id, float) and pd.isna(gsis_id):
            continue
        pfr_str = str(pfr_id).strip()
        gsis_str = str(gsis_id).strip()
        if pfr_str and gsis_str:
            mapping[pfr_str] = gsis_str
    return mapping


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


def _load_snap_counts_frame(season: int) -> pd.DataFrame:
    """Load nflverse snap counts (offense_pct is 0-1 fraction)."""
    snap_counts_url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"snap_counts/snap_counts_{season}.parquet"
    )
    try:
        snaps = pd.read_parquet(snap_counts_url)
        if snaps is not None and not snaps.empty:
            return snaps
    except Exception as exc:
        if not _is_remote_not_found(exc):
            logger.warning(
                "snap_counts_%s.parquet read failed (%s); trying import_snap_counts",
                season,
                exc,
            )

    try:
        import nfl_data_py as nfl
    except ImportError:
        return pd.DataFrame()

    try:
        snaps = nfl.import_snap_counts([season])
    except Exception as exc:
        logger.warning(
            "nflverse import_snap_counts unavailable for %s: %s", season, exc
        )
        return pd.DataFrame()

    if snaps is None or snaps.empty:
        return pd.DataFrame()
    return snaps


def _build_gsis_week_snap_lookup(season: int) -> Dict[Tuple[str, int], float]:
    """Map (GSIS player_id, week) → offense_pct fraction from snap_counts."""
    details = _build_gsis_week_snap_details_lookup(season)
    return {
        key: value["offense_pct"]
        for key, value in details.items()
        if value.get("offense_pct") is not None
    }


def _build_gsis_week_snap_details_lookup(
    season: int,
) -> Dict[Tuple[str, int], Dict[str, Optional[float]]]:
    """Map (GSIS player_id, week) → offense_pct fraction and offense_snaps count."""
    snaps = _load_snap_counts_frame(season)
    if snaps.empty:
        return {}

    pfr_to_gsis = _load_pfr_to_gsis_map()
    if not pfr_to_gsis:
        return {}

    lookup: Dict[Tuple[str, int], Dict[str, Optional[float]]] = {}
    for _, snap_row in snaps.iterrows():
        pfr_id = snap_row.get("pfr_player_id")
        week = _safe_int(snap_row.get("week"))
        offense_pct = _safe_float(snap_row.get("offense_pct"))
        offense_snaps = _safe_float(snap_row.get("offense_snaps"))
        if pfr_id is None or week is None:
            continue
        gsis_id = pfr_to_gsis.get(str(pfr_id).strip())
        if not gsis_id:
            continue
        lookup[(str(gsis_id).strip(), week)] = {
            "offense_pct": offense_pct,
            "offense_snaps": offense_snaps,
        }
    return lookup


def _load_schedules_frame(season: int) -> pd.DataFrame:
    schedules_url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "schedules/games.parquet"
    )
    try:
        schedules = pd.read_parquet(schedules_url)
    except Exception as exc:
        logger.warning("nflverse schedules unavailable for %s: %s", season, exc)
        return pd.DataFrame()

    if schedules is None or schedules.empty:
        return pd.DataFrame()

    filtered = schedules[
        (schedules["season"] == season)
        & (schedules["game_type"] == "REG")
        & schedules["home_score"].notna()
        & schedules["away_score"].notna()
    ].copy()
    return filtered


def _build_team_week_game_script_lookup(season: int) -> Dict[Tuple[str, int], float]:
    """Map (team abbr, week) → final score margin (positive = team won)."""
    schedules = _load_schedules_frame(season)
    if schedules.empty:
        return {}

    lookup: Dict[Tuple[str, int], float] = {}
    for _, game in schedules.iterrows():
        week = _safe_int(game.get("week"))
        home_score = _safe_float(game.get("home_score"))
        away_score = _safe_float(game.get("away_score"))
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        if week is None or home_score is None or away_score is None:
            continue
        if home_team:
            lookup[(str(home_team).strip(), week)] = home_score - away_score
        if away_team:
            lookup[(str(away_team).strip(), week)] = away_score - home_score
    return lookup


def _load_injuries_frame(season: int) -> pd.DataFrame:
    injuries_url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"injuries/injuries_{season}.parquet"
    )
    try:
        injuries = pd.read_parquet(injuries_url)
    except Exception as exc:
        if _is_remote_not_found(exc):
            logger.warning("No nflverse injuries parquet for season %s", season)
        else:
            logger.warning("nflverse injuries unavailable for %s: %s", season, exc)
        return pd.DataFrame()

    if injuries is None or injuries.empty:
        return pd.DataFrame()
    return injuries


def _normalize_injury_designation(status: Any) -> Optional[str]:
    if status is None or (isinstance(status, float) and pd.isna(status)):
        return None
    text = str(status).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"full participation", "active", "healthy"}:
        designation = "Healthy"
    elif "participation" in lowered and "did not" not in lowered:
        designation = "Healthy"
    elif "out" in lowered:
        designation = "Out"
    elif "doubt" in lowered:
        designation = "Doubtful"
    elif "question" in lowered:
        designation = "Questionable"
    else:
        designation = text.title()
    if len(designation) > 20:
        return designation[:20]
    return designation


def _build_gsis_week_injury_lookup(season: int) -> Dict[Tuple[str, int], str]:
    """Map (GSIS player_id, week) → injury designation from nflverse reports."""
    injuries = _load_injuries_frame(season)
    if injuries.empty or "gsis_id" not in injuries.columns:
        return {}

    lookup: Dict[Tuple[str, int], str] = {}
    for _, row in injuries.iterrows():
        gsis_id = row.get("gsis_id")
        week = _safe_int(row.get("week"))
        if gsis_id is None or week is None:
            continue
        status = row.get("report_status") or row.get("practice_status")
        designation = _normalize_injury_designation(status)
        if designation:
            lookup[(str(gsis_id).strip(), week)] = designation
    return lookup


def _load_pbp_red_zone_frame(season: int) -> pd.DataFrame:
    pbp_url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"pbp/play_by_play_{season}.parquet"
    )
    columns = [
        "week",
        "posteam",
        "yardline_100",
        "pass",
        "rush",
        "receiver_player_id",
        "rusher_player_id",
    ]
    try:
        pbp = pd.read_parquet(pbp_url, columns=columns)
    except Exception as exc:
        if _is_remote_not_found(exc):
            logger.warning("No nflverse PBP parquet for season %s", season)
        else:
            logger.warning("nflverse PBP unavailable for %s: %s", season, exc)
        return pd.DataFrame()

    if pbp is None or pbp.empty:
        return pd.DataFrame()

    rz = pbp[pbp["yardline_100"].notna() & (pbp["yardline_100"] <= 20)].copy()
    return rz


def _build_gsis_week_red_zone_lookup(
    season: int,
) -> Dict[Tuple[str, int], Dict[str, Optional[float]]]:
    """Map (GSIS player_id, week) → red-zone usage metrics."""
    rz = _load_pbp_red_zone_frame(season)
    if rz.empty:
        return {}

    team_week_totals: Dict[Tuple[str, int], int] = {}
    for (team, week), group in rz.groupby(["posteam", "week"]):
        if team is None or pd.isna(team):
            continue
        week_int = _safe_int(week)
        if week_int is None:
            continue
        pass_attempts = int((group["pass"] == 1).sum())
        rush_attempts = int((group["rush"] == 1).sum())
        team_week_totals[(str(team).strip(), week_int)] = pass_attempts + rush_attempts

    lookup: Dict[Tuple[str, int], Dict[str, Optional[float]]] = {}

    pass_rz = rz[rz["pass"] == 1]
    for (player_id, week), count in (
        pass_rz.groupby(["receiver_player_id", "week"]).size().items()
    ):
        if player_id is None or pd.isna(player_id):
            continue
        week_int = _safe_int(week)
        if week_int is None:
            continue
        key = (str(player_id).strip(), week_int)
        entry = lookup.setdefault(
            key,
            {
                "red_zone_targets": 0,
                "red_zone_carries": 0,
                "red_zone_touches": 0,
                "red_zone_share": None,
            },
        )
        entry["red_zone_targets"] = int(count)

    rush_rz = rz[rz["rush"] == 1]
    for (player_id, week), count in (
        rush_rz.groupby(["rusher_player_id", "week"]).size().items()
    ):
        if player_id is None or pd.isna(player_id):
            continue
        week_int = _safe_int(week)
        if week_int is None:
            continue
        key = (str(player_id).strip(), week_int)
        entry = lookup.setdefault(
            key,
            {
                "red_zone_targets": 0,
                "red_zone_carries": 0,
                "red_zone_touches": 0,
                "red_zone_share": None,
            },
        )
        entry["red_zone_carries"] = int(count)

    for key, entry in lookup.items():
        targets = int(entry.get("red_zone_targets") or 0)
        carries = int(entry.get("red_zone_carries") or 0)
        touches = targets + carries
        entry["red_zone_touches"] = touches
        gsis_id, week_int = key
        team_key = None
        team_rows = rz[
            (rz["week"] == week_int)
            & (
                (rz["receiver_player_id"] == gsis_id)
                | (rz["rusher_player_id"] == gsis_id)
            )
        ]
        if not team_rows.empty:
            team_key = str(team_rows.iloc[0]["posteam"]).strip()
        team_total = team_week_totals.get((team_key, week_int)) if team_key else None
        if team_total and team_total > 0:
            entry["red_zone_share"] = touches / team_total

    return lookup


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    try:
        quantiles = statistics.quantiles(values, n=100, method="inclusive")
        index = max(0, min(len(quantiles) - 1, int(round(pct)) - 1))
        return quantiles[index]
    except statistics.StatisticsError:
        return values[0]


def _apply_season_consistency_metrics(payloads: List[Dict[str, Any]]) -> None:
    """Attach cumulative boom/bust/floor/ceiling through each played week."""
    by_player: Dict[int, List[Dict[str, Any]]] = {}
    for payload in payloads:
        by_player.setdefault(payload["player_id"], []).append(payload)

    for player_payloads in by_player.values():
        player_payloads.sort(key=lambda row: row["week"])
        ppr_history: List[float] = []
        for payload in player_payloads:
            ppr = payload.get("ppr_points")
            if ppr is not None:
                ppr_history.append(float(ppr))
            games = len(ppr_history)
            if games == 0:
                continue
            payload["boom_rate"] = round(
                100.0 * sum(1 for score in ppr_history if score >= 20.0) / games,
                2,
            )
            payload["bust_rate"] = round(
                100.0 * sum(1 for score in ppr_history if score < 5.0) / games,
                2,
            )
            floor_score = _percentile(ppr_history, 25)
            ceiling_score = _percentile(ppr_history, 75)
            payload["floor_score"] = (
                round(floor_score, 2) if floor_score is not None else None
            )
            payload["ceiling_score"] = (
                round(ceiling_score, 2) if ceiling_score is not None else None
            )


def _load_existing_rows(
    db: Session, season: int
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """Map (player_id, week) → existing row snapshot for one season."""
    rows = (
        db.query(PlayerAnalytics)
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
    snap_lookup: Optional[Dict[Tuple[str, int], float]] = None,
    snap_details_lookup: Optional[
        Dict[Tuple[str, int], Dict[str, Optional[float]]]
    ] = None,
    red_zone_lookup: Optional[Dict[Tuple[str, int], Dict[str, Optional[float]]]] = None,
    game_script_lookup: Optional[Dict[Tuple[str, int], float]] = None,
    injury_lookup: Optional[Dict[Tuple[str, int], str]] = None,
) -> Dict[str, Any]:
    ppr_points = _compute_ppr_points(row)
    targets = _safe_int(row.get("targets")) or 0
    carries = _safe_int(row.get("carries")) or 0
    receptions = _safe_int(row.get("receptions")) or 0
    receiving_yards = _safe_int(row.get("receiving_yards")) or 0
    rushing_yards = _safe_int(row.get("rushing_yards")) or 0
    gsis_id = str(row.get("player_id", "")).strip()
    team = row.get("recent_team") or row.get("team")

    offense_pct = _safe_float(row.get("offense_pct"))
    offensive_snaps: Optional[int] = None
    snap_key = (gsis_id, week)
    if snap_details_lookup and snap_key in snap_details_lookup:
        snap_detail = snap_details_lookup[snap_key]
        if offense_pct is None:
            offense_pct = snap_detail.get("offense_pct")
        snap_count = snap_detail.get("offense_snaps")
        if snap_count is not None:
            offensive_snaps = int(snap_count)
    elif offense_pct is None and snap_lookup is not None:
        offense_pct = snap_lookup.get(snap_key)

    red_zone_targets = 0
    red_zone_carries = 0
    red_zone_touches = 0
    red_zone_share: Optional[float] = None
    if red_zone_lookup and snap_key in red_zone_lookup:
        rz = red_zone_lookup[snap_key]
        red_zone_targets = int(rz.get("red_zone_targets") or 0)
        red_zone_carries = int(rz.get("red_zone_carries") or 0)
        red_zone_touches = int(rz.get("red_zone_touches") or 0)
        red_zone_share = _safe_float(rz.get("red_zone_share"))

    game_script: Optional[float] = None
    if game_script_lookup and team is not None:
        game_script = game_script_lookup.get((str(team).strip(), week))

    injury_designation: Optional[str] = None
    if injury_lookup:
        injury_designation = injury_lookup.get(snap_key)

    points_per_snap: Optional[float] = None
    if offensive_snaps and offensive_snaps > 0:
        points_per_snap = round(ppr_points / offensive_snaps, 4)

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
        "snap_percentage": _normalize_snap_percentage(offense_pct),
        "offensive_snaps": offensive_snaps,
        "points_per_target": (ppr_points / targets if targets > 0 else None),
        "points_per_snap": points_per_snap,
        "red_zone_targets": red_zone_targets,
        "red_zone_carries": red_zone_carries,
        "red_zone_touches": red_zone_touches,
        "red_zone_share": red_zone_share,
        "game_script": game_script,
        "injury_designation": injury_designation,
        "boom_rate": None,
        "bust_rate": None,
        "floor_score": None,
        "ceiling_score": None,
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
    snap_details_lookup = _build_gsis_week_snap_details_lookup(season)
    red_zone_lookup = _build_gsis_week_red_zone_lookup(season)
    game_script_lookup = _build_team_week_game_script_lookup(season)
    injury_lookup = _build_gsis_week_injury_lookup(season)
    payloads: List[Dict[str, Any]] = []
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

        payloads.append(
            _row_payload(
                row=row,
                fantasy_player_id=fantasy_player_id,
                week=week,
                season=season,
                snap_details_lookup=snap_details_lookup,
                red_zone_lookup=red_zone_lookup,
                game_script_lookup=game_script_lookup,
                injury_lookup=injury_lookup,
            )
        )

    _apply_season_consistency_metrics(payloads)

    for payload in payloads:
        fantasy_player_id = payload["player_id"]
        week = payload["week"]
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
