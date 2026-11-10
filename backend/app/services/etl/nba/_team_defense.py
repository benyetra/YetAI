"""What opponents average against a team, as of any date.

``pred_team_defense_stats`` holds one row per team: its defense *today*. The
prop models read it as the ``opp_*`` features, which is right for tonight's
slate but not for training: every historical game was paired with the
opponent's present-day defense, so a January 2025 game against a team that
was a top-five defense then saw whatever that team is this month. The model
could not learn a matchup effect from that.

``team_defense_as_of`` computes the same numbers from ``pred_recent_games``
for games before a given date. ``update_team_defense_stats`` stores its result
for "tomorrow" (everything played so far) and the feature builder asks for
each row's own game date, so a row in training and a row on tonight's slate
are built the same way.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func

from app.models.predictions_models import RecentGames
from app.services.etl.nba._samples import MIN_CURRENT_SEASON_GAMES
from app.services.etl.nba._season import season_opener

# Last N games each team appeared in as the opponent (~60 days in-season),
# this season's only once there is any current-season game. A game count
# rather than a date window: opening night still reaches back into last
# season instead of averaging an empty slate.
LOOKBACK_GAMES = 25
LEAGUE_AVG_DRTG = 114.0
LEAGUE_AVG_TRACKED_PTS = 95.0

_SUMS = {
    "points": RecentGames.points,
    "assists": RecentGames.assists,
    "rebounds": RecentGames.rebounds,
    "oreb": RecentGames.offensive_rebounds,
    "dreb": RecentGames.defensive_rebounds,
    "tpm": RecentGames.three_pt_made,
    "tpa": RecentGames.three_pt_attempts,
    "ftm": RecentGames.free_throws_made,
    "steals": RecentGames.steals,
    "blocks": RecentGames.blocks,
    "turnovers": RecentGames.turnovers,
    "fouls": RecentGames.personal_fouls,
    "fg_pct_sum": RecentGames.fg_percentage,
}

# Finished games do not change, so (team, date) answers for past dates are
# reused: a training build asks for each of them hundreds of times.
_cache: dict[tuple[int, date], dict[str, Any] | None] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 50_000


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _compute(db, team_id: int, before: date) -> dict[str, Any] | None:
    per_game = (
        db.query(
            RecentGames.game_date,
            func.count(RecentGames.fg_percentage).label("fg_pct_n"),
            *[func.sum(col).label(name) for name, col in _SUMS.items()],
        )
        .filter(
            RecentGames.opponent_team_id == team_id,
            RecentGames.game_date < before,
        )
        .group_by(RecentGames.game_date)
        .order_by(RecentGames.game_date.desc())
        .limit(LOOKBACK_GAMES)
        .all()
    )
    opener = season_opener(before - timedelta(days=1))
    this_season = [g for g in per_game if g.game_date >= opener]
    if len(this_season) >= MIN_CURRENT_SEASON_GAMES:
        per_game = this_season
    games = len(per_game)
    if not games:
        return None

    totals = {
        name: sum(float(getattr(g, name) or 0) for g in per_game) for name in _SUMS
    }
    fg_pct_rows = sum(int(g.fg_pct_n or 0) for g in per_game)

    def avg(name: str) -> float:
        return round(totals[name] / games, 1)

    data: dict[str, Any] = {
        "games": games,
        "points_allowed_per_game": avg("points"),
        "assists_allowed_per_game": avg("assists"),
        "rebounds_allowed_per_game": avg("rebounds"),
        "offensive_rebounds_allowed_per_game": avg("oreb"),
        "defensive_rebounds": avg("dreb"),
        "three_pt_made_allowed_per_game": avg("tpm"),
        "three_pt_attempted_allowed_per_game": avg("tpa"),
        "free_throws_allowed_per_game": avg("ftm"),
        "steals": avg("steals"),
        "blocks": avg("blocks"),
        "turnovers": avg("turnovers"),
        "personal_fouls": avg("fouls"),
    }
    if totals["tpa"] > 0:
        data["three_pt_pct_allowed"] = round(totals["tpm"] / totals["tpa"], 3)
    if fg_pct_rows and totals["fg_pct_sum"]:
        data["field_goal_pct_allowed"] = round(totals["fg_pct_sum"] / fg_pct_rows, 3)

    pts = data["points_allowed_per_game"]
    data["defensive_rating"] = (
        round(LEAGUE_AVG_DRTG * pts / LEAGUE_AVG_TRACKED_PTS, 1)
        if pts > 0
        else LEAGUE_AVG_DRTG
    )
    return data


def team_defense_as_of(db, team_id: int, before: date) -> dict[str, Any] | None:
    """Per-game averages opponents put up against ``team_id`` over its last
    ``LOOKBACK_GAMES`` games before ``before`` (keys match the
    ``TeamDefenseStats`` columns, plus ``games``). None with no games."""
    key = (int(team_id), before)
    cacheable = before < date.today()
    if cacheable:
        with _cache_lock:
            if key in _cache:
                return _cache[key]
    data = _compute(db, int(team_id), before)
    if cacheable:
        with _cache_lock:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[key] = data
    return data
