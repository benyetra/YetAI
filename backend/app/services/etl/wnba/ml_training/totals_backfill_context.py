"""Bulk in-memory context for fast WNBA totals projection backfill."""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models.predictions_models import WNBARecentGames, WNBATeamRoster
from app.services.etl.wnba import totals_projector as tp
from app.services.etl.wnba.ml_training import team_stats_as_of as tsa
from app.services.etl.wnba.ml_training.team_stats_as_of import DEFAULT_LOOKBACK_DAYS


@dataclass
class TotalsBackfillContext:
    """Preloaded player/team history to avoid N+1 DB queries during backfill."""

    stats_cache: tsa.TeamStatsCache
    team_name_to_id: dict[str, int] = field(default_factory=dict)
    team_player_ids: dict[int, list[int]] = field(default_factory=dict)
    player_points_by_date: dict[int, list[tuple[date, float]]] = field(
        default_factory=dict
    )
    team_game_dates: dict[int, list[date]] = field(default_factory=dict)


def _points_series(games: list[tuple[date, float]]) -> list[float]:
    return [pts for _, pts in games]


def build_context(
    db,
    season_start: date,
    season_end: date,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> TotalsBackfillContext:
    """Load roster + recent games once for rest/form replay."""
    tp.db = db
    tp.TEAM_NAME_TO_ID.clear()
    tp.TEAM_ID_TO_NAME.clear()
    tp.load_team_data()

    team_name_to_id = {name.lower(): tid for name, tid in tp.TEAM_NAME_TO_ID.items()}
    player_to_team = {
        row.player_id: row.team_id for row in db.query(WNBATeamRoster).all()
    }
    team_player_ids: dict[int, list[int]] = defaultdict(list)
    for player_id, team_id in player_to_team.items():
        team_player_ids[team_id].append(player_id)

    lookback_start = season_start - timedelta(days=lookback_days)
    games = (
        db.query(WNBARecentGames)
        .filter(WNBARecentGames.game_date >= lookback_start)
        .filter(WNBARecentGames.game_date <= season_end)
        .all()
    )

    player_points_by_date: dict[int, list[tuple[date, float]]] = defaultdict(list)
    team_date_sets: dict[int, set[date]] = defaultdict(set)

    for game in games:
        if game.points is None:
            continue
        try:
            pts = float(game.points)
        except (TypeError, ValueError):
            continue
        player_points_by_date[game.player_id].append((game.game_date, pts))
        team_id = player_to_team.get(game.player_id)
        if team_id is not None:
            team_date_sets[team_id].add(game.game_date)

    for player_id in player_points_by_date:
        player_points_by_date[player_id].sort(key=lambda item: item[0])

    team_game_dates = {
        team_id: sorted(dates) for team_id, dates in team_date_sets.items()
    }
    stats_cache = tsa.build_cache(db, season_start, season_end)

    return TotalsBackfillContext(
        stats_cache=stats_cache,
        team_name_to_id=team_name_to_id,
        team_player_ids=dict(team_player_ids),
        player_points_by_date=dict(player_points_by_date),
        team_game_dates=team_game_dates,
    )


def _team_id(ctx: TotalsBackfillContext, team_name: str) -> int | None:
    return ctx.team_name_to_id.get(team_name.lower())


def _last_team_game_before(
    ctx: TotalsBackfillContext, team_name: str, as_of: date
) -> date | None:
    team_id = _team_id(ctx, team_name)
    if team_id is None:
        return None
    dates = ctx.team_game_dates.get(team_id, [])
    if not dates:
        return None
    idx = bisect.bisect_left(dates, as_of) - 1
    if idx < 0:
        return None
    return dates[idx]


def rest_adjustment_as_of(
    ctx: TotalsBackfillContext,
    home_team: str,
    away_team: str,
    game_date: date,
) -> float:
    """In-memory port of ``calculate_rest_adjustment``."""
    adjustment = 0.0
    for team_name in (home_team, away_team):
        recent = _last_team_game_before(ctx, team_name, game_date)
        if recent is None:
            continue
        days_rest = (game_date - recent).days
        if days_rest == 1:
            adjustment -= 2.0
        elif days_rest == 0:
            adjustment -= 3.0
        elif days_rest >= 4:
            adjustment += 0.5
    return max(-5.0, min(adjustment, 2.0))


def team_form_as_of(
    ctx: TotalsBackfillContext,
    team_name: str,
    as_of: date,
    *,
    num_recent_games: int = 5,
) -> float:
    """In-memory port of ``calculate_team_form_as_of``."""
    team_id = _team_id(ctx, team_name)
    if team_id is None:
        return 0.0

    total_deviation = 0.0
    for player_id in ctx.team_player_ids.get(team_id, []):
        games = ctx.player_points_by_date.get(player_id, [])
        if not games:
            continue
        idx = bisect.bisect_left(games, (as_of, float("-inf")))
        prior = games[:idx]
        if len(prior) < 5:
            continue

        season_points = _points_series(prior)
        season_avg_ppg = sum(season_points) / len(season_points)
        if season_avg_ppg < 5.0:
            continue

        recent = prior[-num_recent_games:]
        recent_avg_ppg = sum(_points_series(recent)) / len(recent)
        total_deviation += recent_avg_ppg - season_avg_ppg

    return max(-8.0, min(total_deviation, 8.0))


def form_adjustment_as_of(
    ctx: TotalsBackfillContext,
    home_team: str,
    away_team: str,
    game_date: date,
) -> float:
    home_form = team_form_as_of(ctx, home_team, game_date)
    away_form = team_form_as_of(ctx, away_team, game_date)
    total_form = home_form + away_form
    return max(-10.0, min(total_form, 10.0))
