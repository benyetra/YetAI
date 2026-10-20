"""NBA league calendar helpers shared by the ETL modules.

The league year rolls over in October, but the first weeks of October are
preseason and July–September is Summer League / offseason. Box scores from
those windows must not land in pred_recent_games: they feed every rolling
average (props, expected minutes, team defense), and preseason minutes in
particular drag down starters' projections on opening night.
"""

from __future__ import annotations

from datetime import date, timedelta

# Regular-season opening night by league year (season starting in that year).
# Add the new date each summer once the NBA releases the schedule; unknown
# years fall back to `_estimated_regular_season_start`.
REGULAR_SEASON_START: dict[int, date] = {
    2023: date(2023, 10, 24),
    2024: date(2024, 10, 22),
    2025: date(2025, 10, 21),
    2026: date(2026, 10, 20),
}

# Playoffs finish in June; anything from July 1 until opening night is
# Summer League, preseason, or dead time.
OFFSEASON_START_MONTH_DAY = (7, 1)


def season_start_year(d: date) -> int:
    """League year a date belongs to (2026 for the 2026-27 season)."""
    return d.year if d.month >= 10 else d.year - 1


def season_label(start_year: int) -> str:
    """'2026-27' style label used by pred_player_career_data.season."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def api_basketball_season(d: date) -> str:
    """'2026-2027' style season used by API-Basketball (v1) league 12."""
    start = season_start_year(d)
    return f"{start}-{start + 1}"


def _estimated_regular_season_start(year: int) -> date:
    """Opening night is the Tuesday on or after Oct 18 (true for 2022–2026)."""
    d = date(year, 10, 18)
    return d + timedelta(days=(1 - d.weekday()) % 7)


def regular_season_start(year: int) -> date:
    return REGULAR_SEASON_START.get(year) or _estimated_regular_season_start(year)


def is_offseason_date(d: date) -> bool:
    """True for Summer League / preseason dates (July 1 → day before opening night)."""
    offseason_start = date(d.year, *OFFSEASON_START_MONTH_DAY)
    return offseason_start <= d < regular_season_start(d.year)


def offseason_window(year: int) -> tuple[date, date]:
    """Inclusive (first, last) offseason dates for the summer of `year`."""
    return (
        date(year, *OFFSEASON_START_MONTH_DAY),
        regular_season_start(year) - timedelta(days=1),
    )
