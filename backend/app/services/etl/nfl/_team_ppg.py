"""Team points-per-game stats from NFL spread actuals."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Sequence

from app.services.etl._spread_model import SpreadActualRow

LEAGUE_AVG_PPG = 22.5
MIN_GAMES_FOR_PPG = 1
# Prefer current-season PPG once a team has this many games; otherwise fall
# back to the prior season (early-season cold start).
MIN_SEASON_GAMES_FOR_PPG = 4
# NFL regular season spans Sep (calendar year = season) through Feb (+1).
NFL_SEASON_START_MONTH = 9


def nfl_season_id_for_date(game_date: date) -> int:
    """Map a game date to its NFL season year (September-start)."""
    if game_date.month >= NFL_SEASON_START_MONTH:
        return game_date.year
    return game_date.year - 1


def _game_date(game: SpreadActualRow) -> date | None:
    raw = getattr(game, "game_date", None)
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    return None


def _actuals_for_season(
    actuals: Sequence[SpreadActualRow], season: int
) -> list[SpreadActualRow]:
    matched: list[SpreadActualRow] = []
    for game in actuals:
        gd = _game_date(game)
        if gd is not None and nfl_season_id_for_date(gd) == season:
            matched.append(game)
    return matched


def _accumulate_ppg(
    actuals: Sequence[SpreadActualRow],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
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

    return points_for, points_against, games


def _stats_from_accum(
    points_for: dict[str, float],
    points_against: dict[str, float],
    games: dict[str, int],
    *,
    min_games: int = MIN_GAMES_FOR_PPG,
) -> dict[str, tuple[float, float]]:
    stats: dict[str, tuple[float, float]] = {}
    for team, n in games.items():
        if n >= min_games:
            stats[team] = (points_for[team] / n, points_against[team] / n)
    return stats


def compute_team_ppg_stats(
    actuals: Sequence[SpreadActualRow],
    *,
    season: int | None = None,
    min_season_games: int = MIN_SEASON_GAMES_FOR_PPG,
) -> dict[str, tuple[float, float]]:
    """Return ``{team_name: (ppg_for, ppg_against)}`` from game history.

    When ``season`` is set, prefer that season's games so mid-season form is
    not drowned by multi-year seed history. Teams with fewer than
    ``min_season_games`` in the target season fall back to the prior season's
    PPG (early-season cold start). Rows without ``game_date`` are ignored when
    filtering by season.
    """
    if season is None:
        pf, pa, games = _accumulate_ppg(actuals)
        return _stats_from_accum(pf, pa, games)

    season_actuals = _actuals_for_season(actuals, season)
    season_pf, season_pa, season_games = _accumulate_ppg(season_actuals)
    season_stats = _stats_from_accum(season_pf, season_pa, season_games)

    prior_actuals = _actuals_for_season(actuals, season - 1)
    prior_pf, prior_pa, prior_games = _accumulate_ppg(prior_actuals)
    prior_stats = _stats_from_accum(prior_pf, prior_pa, prior_games)

    teams = set(season_games) | set(prior_games)
    stats: dict[str, tuple[float, float]] = {}
    for team in teams:
        if season_games.get(team, 0) >= min_season_games and team in season_stats:
            stats[team] = season_stats[team]
        elif team in prior_stats:
            stats[team] = prior_stats[team]
        elif team in season_stats:
            # Thin current-season sample and no prior — still better than league avg.
            stats[team] = season_stats[team]
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
