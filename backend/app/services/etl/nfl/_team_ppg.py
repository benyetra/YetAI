"""Team points-per-game stats from NFL spread actuals."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from app.services.etl._spread_model import SpreadActualRow

LEAGUE_AVG_PPG = 22.5
MIN_GAMES_FOR_PPG = 1


def compute_team_ppg_stats(
    actuals: Sequence[SpreadActualRow],
) -> dict[str, tuple[float, float]]:
    """Return ``{team_name: (ppg_for, ppg_against)}`` from game history."""
    points_for: dict[str, float] = defaultdict(float)
    points_against: dict[str, float] = defaultdict(float)
    games: dict[str, int] = defaultdict(int)

    for game in actuals:
        points_for[game.home_team_name] += game.home_score
        points_against[game.home_team_name] += game.away_score
        games[game.home_team_name] += 1

        points_for[game.away_team_name] += game.away_score
        points_against[game.away_team_name] += game.home_score
        games[game.away_team_name] += 1

    stats: dict[str, tuple[float, float]] = {}
    for team, n in games.items():
        if n >= MIN_GAMES_FOR_PPG:
            stats[team] = (points_for[team] / n, points_against[team] / n)
    return stats


def team_ppg_for(
    team_name: str,
    ppg_stats: dict[str, tuple[float, float]],
    *,
    league_avg: float = LEAGUE_AVG_PPG,
) -> tuple[float, float]:
    """Return ``(ppg_for, ppg_against)`` using league average when data is thin."""
    if team_name in ppg_stats:
        return ppg_stats[team_name]
    return league_avg, league_avg
