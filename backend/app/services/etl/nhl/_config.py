"""NHL ETL season and league-average defaults (env + DB-backed)."""

from __future__ import annotations

import os

from app.models.predictions_models import NHLTeamStats
from app.services.etl.nhl._db import db_session

DEFAULT_NHL_SEASON = 20252026

# Fallback constants when pred_nhl_team_stats is empty or a field is null.
DEFAULT_SHOTS_AGAINST = 30.0
DEFAULT_SHOTS_FOR = 30.0
DEFAULT_SHOOTING_PCT = 0.10
DEFAULT_BLOCKED_SHOTS_PER_GAME = 15.0
DEFAULT_GOALS_FOR_PER_GAME = 3.0
DEFAULT_GOALS_AGAINST_PER_GAME = 3.0


def get_nhl_season() -> int:
    """Current NHL season id (YYYYYYYY), e.g. 20252026 for 2025-26."""
    raw = os.environ.get("NHL_SEASON", str(DEFAULT_NHL_SEASON))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_NHL_SEASON


def _resolve_season(season: int | None) -> int:
    return season if season is not None else get_nhl_season()


def team_stat_or_default(team_id: int, field: str, default: float) -> float:
    """Return a team stat from pred_nhl_team_stats or the provided default."""
    row = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()
    if row is None:
        return default
    value = getattr(row, field, None)
    if value is None:
        return default
    return float(value)


def _league_average(field: str, fallback: float) -> float:
    """Mean of a per-game stat across teams with data, else fallback constant."""
    column = getattr(NHLTeamStats, field, None)
    if column is None:
        return fallback
    values = [
        float(row[0])
        for row in db_session.query(column).filter(column.isnot(None)).all()
        if row[0] is not None
    ]
    if not values:
        return fallback
    return sum(values) / len(values)


def get_league_avg_shots_against() -> float:
    return _league_average("shots_against_per_game", DEFAULT_SHOTS_AGAINST)


def get_league_avg_shots_for() -> float:
    return _league_average("shots_for_per_game", DEFAULT_SHOTS_FOR)


def get_league_avg_shooting_pct() -> float:
    return _league_average("shooting_pct", DEFAULT_SHOOTING_PCT)


def get_league_avg_blocked_shots_per_game() -> float:
    return _league_average("blocked_shots_per_game", DEFAULT_BLOCKED_SHOTS_PER_GAME)


def get_league_avg_combined_shots_pace() -> float:
    """Typical combined shots/game (home + away) for pace adjustments."""
    return get_league_avg_shots_for() * 2.0


def team_shots_against(team_id: int) -> float:
    return team_stat_or_default(
        team_id, "shots_against_per_game", get_league_avg_shots_against()
    )


def team_shots_for(team_id: int) -> float:
    return team_stat_or_default(
        team_id, "shots_for_per_game", get_league_avg_shots_for()
    )


def team_shooting_pct(team_id: int) -> float:
    return team_stat_or_default(team_id, "shooting_pct", get_league_avg_shooting_pct())
