"""Shared NFL calendar helpers (ported from YetiBets scripts/nfl)."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_NFL_SEASON = 2026


def get_nfl_season() -> int:
    """Current NFL season year (calendar year season starts in September)."""
    raw = os.environ.get("NFL_SEASON", str(DEFAULT_NFL_SEASON))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_NFL_SEASON


def resolve_nfl_season(season: int | None) -> int:
    return season if season is not None else get_nfl_season()


def get_current_season() -> int:
    """Alias for active season; prefer ``get_nfl_season()`` for config override."""
    return get_nfl_season()


def _first_regular_season_thursday(season: int) -> date:
    labor_day = date(season, 9, 1)
    while labor_day.weekday() != 0:
        labor_day = date(season, 9, labor_day.day + 1)

    first_thursday = labor_day + timedelta(days=3)
    if first_thursday.day > 10:
        first_thursday = first_thursday - timedelta(days=7)
    return first_thursday


def get_current_nfl_week(
    season: int | None = None, *, today: date | None = None
) -> int:
    """Regular-season week 1–18 from today's date (or ``today`` for tests)."""
    ref = today if today is not None else date.today()
    resolved_season = resolve_nfl_season(season)

    first_thursday = _first_regular_season_thursday(resolved_season)
    if ref < first_thursday:
        return 1

    days_since_start = (ref - first_thursday).days
    current_week = (days_since_start // 7) + 1
    return min(max(current_week, 1), 18)


EASTERN = ZoneInfo("America/New_York")


def now_eastern_naive() -> datetime:
    """Current wall-clock time in US Eastern, without tzinfo (nflverse kickoffs
    and the stored ``game_date`` columns are naive Eastern times)."""
    return datetime.now(EASTERN).replace(tzinfo=None)


def has_kicked_off(
    kickoff: datetime | date | None, *, now: datetime | None = None
) -> bool:
    """True once a game's scheduled kickoff has passed.

    The weekly pipeline runs every day, and the NFL week only rolls over on
    Thursday, so Monday-Wednesday runs still point at games already played.
    Their rows must stay as they were at kickoff: those are the numbers (and
    the closing line) the pick is graded against. Unknown kickoff -> False.
    A bare date counts as kicked off from the following day.
    """
    if kickoff is None:
        return False
    current = now if now is not None else now_eastern_naive()
    if isinstance(kickoff, datetime):
        return kickoff.replace(tzinfo=None) <= current
    return kickoff < current.date()
