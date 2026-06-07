"""Point-in-time WNBA team pace/efficiency from player game logs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean
from typing import Any

from app.models.predictions_models import WNBARecentGames, WNBATeamRoster
from app.services.etl.wnba import totals_projector as tp

DEFAULT_MAX_GAMES = 15
DEFAULT_LOOKBACK_DAYS = 730


def _default_stats() -> dict[str, float]:
    return {
        "pace": tp.LEAGUE_AVG_PACE,
        "offensive_rating": tp.LEAGUE_AVG_ORTG,
        "defensive_rating": tp.LEAGUE_AVG_DRTG,
    }


@dataclass
class TeamStatsCache:
    """Preloaded team game logs for fast as-of lookups."""

    team_name_to_id: dict[str, int] = field(default_factory=dict)
    by_team: dict[int, list[tuple[date, dict[str, float]]]] = field(
        default_factory=dict
    )
    max_games: int = DEFAULT_MAX_GAMES


def _mean_or(default: float, values: list[float]) -> float:
    return float(mean(values)) if values else default


def build_cache(
    db,
    season_start: date,
    season_end: date,
    *,
    max_games: int = DEFAULT_MAX_GAMES,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> TeamStatsCache:
    """Bulk-load roster + recent games and index team stats by game date."""
    tp.db = db
    tp.TEAM_NAME_TO_ID.clear()
    tp.TEAM_ID_TO_NAME.clear()
    tp.load_team_data()

    team_name_to_id = {name.lower(): tid for name, tid in tp.TEAM_NAME_TO_ID.items()}
    player_to_team = {
        row.player_id: row.team_id for row in db.query(WNBATeamRoster).all()
    }

    lookback_start = season_start - timedelta(days=lookback_days)
    games = (
        db.query(WNBARecentGames)
        .filter(WNBARecentGames.game_date >= lookback_start)
        .filter(WNBARecentGames.game_date <= season_end)
        .all()
    )

    grouped: dict[tuple[int, date], list[WNBARecentGames]] = defaultdict(list)
    for game in games:
        team_id = player_to_team.get(game.player_id)
        if team_id is None:
            continue
        grouped[(team_id, game.game_date)].append(game)

    by_team: dict[int, list[tuple[date, dict[str, float]]]] = defaultdict(list)
    for (team_id, game_date), rows in grouped.items():
        pace_vals = [float(r.pace) for r in rows if r.pace is not None]
        ortg_vals = [
            float(r.offensive_rating) for r in rows if r.offensive_rating is not None
        ]
        drtg_vals = [
            float(r.defensive_rating) for r in rows if r.defensive_rating is not None
        ]
        by_team[team_id].append(
            (
                game_date,
                {
                    "pace": _mean_or(tp.LEAGUE_AVG_PACE, pace_vals),
                    "offensive_rating": _mean_or(tp.LEAGUE_AVG_ORTG, ortg_vals),
                    "defensive_rating": _mean_or(tp.LEAGUE_AVG_DRTG, drtg_vals),
                },
            )
        )

    for team_id in by_team:
        by_team[team_id].sort(key=lambda item: item[0])

    return TeamStatsCache(
        team_name_to_id=team_name_to_id,
        by_team=dict(by_team),
        max_games=max_games,
    )


def pace_and_efficiency_as_of(
    cache: TeamStatsCache,
    team_name: str,
    as_of: date,
) -> dict[str, float]:
    """Team pace/ORTG/DRTG using only games strictly before ``as_of``."""
    team_id = cache.team_name_to_id.get(team_name.lower())
    if team_id is None:
        return _default_stats()

    history = cache.by_team.get(team_id, [])
    prior = [(game_date, stats) for game_date, stats in history if game_date < as_of]
    if not prior:
        return _default_stats()

    window = prior[-cache.max_games :]
    return {
        "pace": _mean_or(tp.LEAGUE_AVG_PACE, [s["pace"] for _, s in window]),
        "offensive_rating": _mean_or(
            tp.LEAGUE_AVG_ORTG, [s["offensive_rating"] for _, s in window]
        ),
        "defensive_rating": _mean_or(
            tp.LEAGUE_AVG_DRTG, [s["defensive_rating"] for _, s in window]
        ),
    }


def preload_team_stats(
    db,
    season_start: date,
    season_end: date,
) -> dict[str, dict[str, float]]:
    """
    Legacy-shaped cache: team_name.lower() -> callable lookup via nested as-of map.

    Prefer ``build_cache`` + ``pace_and_efficiency_as_of`` for training replay.
    """
    cache = build_cache(db, season_start, season_end)
    return {
        name: pace_and_efficiency_as_of(cache, name, season_end)
        for name in cache.team_name_to_id
    }
