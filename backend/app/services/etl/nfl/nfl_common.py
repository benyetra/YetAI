"""Shared NFL calendar helpers (ported from YetiBets scripts/nfl)."""

from __future__ import annotations

from datetime import date, timedelta


def get_current_season() -> int:
    today = date.today()
    return today.year if today.month >= 9 else today.year - 1


def get_current_nfl_week(season: int | None = None) -> int:
    today = date.today()
    if season is None:
        season = get_current_season()

    labor_day = date(season, 9, 1)
    while labor_day.weekday() != 0:
        labor_day = date(season, 9, labor_day.day + 1)

    first_thursday = labor_day + timedelta(days=3)
    if first_thursday.day > 10:
        first_thursday = first_thursday - timedelta(days=7)

    if today < first_thursday:
        return 1

    days_since_start = (today - first_thursday).days
    current_week = (days_since_start // 7) + 1
    return min(max(current_week, 1), 18)
