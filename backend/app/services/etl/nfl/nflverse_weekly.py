"""nflverse weekly player stats for any season, as one DataFrame schema.

nfl_data_py's ``import_weekly_data`` reads ``player_stats_{season}.parquet``,
which nflverse stopped publishing after 2024 (HTTP 404 for 2025+). Newer
seasons live under ``stats_player/stats_player_week_{season}.parquet`` with a
few renamed columns (``team`` for ``recent_team``, ``sacks_suffered`` for
``sacks``, ``passing_interceptions`` for ``interceptions``). Callers that only
tried the legacy import silently lost every current-season game: QB rolling
form, opponent pass defense and receiver usage all fell back to defaults.

``load_weekly_frame`` tries the legacy import, then the new release, and
returns the legacy column names either way.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

STATS_PLAYER_WEEK_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.parquet"
)

# new release name -> legacy name the ETL code reads
_LEGACY_ALIASES = {
    "team": "recent_team",
    "sacks_suffered": "sacks",
    "passing_interceptions": "interceptions",
    "sack_yards_lost": "sack_yards",
}


def normalize_weekly_frame(frame: Any) -> Any:
    """Add the legacy column names to a ``stats_player_week`` frame (no-op on
    a legacy frame). Existing columns are never overwritten."""
    if frame is None or not hasattr(frame, "columns"):
        return frame
    missing = {
        new: old
        for new, old in _LEGACY_ALIASES.items()
        if new in frame.columns and old not in frame.columns
    }
    if not missing:
        return frame
    out = frame.copy()
    for new, old in missing.items():
        out[old] = out[new]
    return out


def _read_legacy(season: int) -> Any:
    import nfl_data_py as nfl

    return nfl.import_weekly_data([int(season)])


def _read_stats_player_week(season: int) -> Any:
    import pandas as pd

    return pd.read_parquet(STATS_PLAYER_WEEK_URL.format(season=int(season)))


def load_weekly_frame(
    season: int,
    *,
    legacy_reader: Callable[[int], Any] | None = None,
    release_reader: Callable[[int], Any] | None = None,
) -> Any:
    """Weekly player rows for ``season`` (all positions, REG and POST), or
    None when neither source has the season yet. Never raises."""
    readers = (
        ("player_stats", legacy_reader or _read_legacy),
        ("stats_player_week", release_reader or _read_stats_player_week),
    )
    for label, reader in readers:
        try:
            frame = reader(int(season))
        except Exception as exc:
            logger.info("nflverse %s unavailable for %s: %s", label, season, exc)
            continue
        if frame is None or getattr(frame, "empty", True):
            continue
        return normalize_weekly_frame(frame)
    logger.warning("nflverse weekly stats unavailable for season %s", season)
    return None


def _opt_float(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value is None or value != value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def weekly_qb_records(weekly: Any) -> list[dict]:
    """Regular-season QB passing rows from an nflverse weekly frame, in the
    record shape the QB feature helpers read."""
    if weekly is None or getattr(weekly, "empty", True):
        return []
    frame = weekly
    if "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    if "position" in frame.columns:
        frame = frame[frame["position"].fillna("QB").str.upper() == "QB"]
    records: list[dict] = []
    for row in frame.to_dict(orient="records"):
        attempts = _opt_float(row, "attempts")
        if not attempts or attempts < 1:
            continue  # no passes thrown: nothing to learn about a start
        yards = _opt_float(row, "passing_yards") or 0.0
        records.append(
            {
                "qb_player_id": str(row.get("player_id") or ""),
                "qb_player_name": str(
                    row.get("player_display_name") or row.get("player_name") or ""
                ),
                "season": int(row.get("season") or 0),
                "week": int(row.get("week") or 0),
                "actual_passing_yards": yards,
                "recent_team": str(row.get("recent_team") or row.get("team") or ""),
                "opponent_team": str(row.get("opponent_team") or ""),
                "position": "QB",
                "passing_yards": yards,
                "passing_epa": _opt_float(row, "passing_epa"),
                "attempts": attempts,
                "completions": _opt_float(row, "completions"),
                "sacks": _opt_float(row, "sacks"),
                "passing_air_yards": _opt_float(row, "passing_air_yards"),
            }
        )
    return records
