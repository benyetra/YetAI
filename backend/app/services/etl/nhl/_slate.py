"""Eastern-time slate helpers for NHL ETL (schedule, game_date, re-run cleanup)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.etl.nba._espn import now_eastern

EASTERN = ZoneInfo("America/New_York")


def game_datetime_et(
    game: dict, default_slate: date | None = None
) -> tuple[date, datetime | None]:
    """Return (game_date_et, game_time_et naive) from NHL schedule payload."""
    slate = default_slate or now_eastern().date()
    raw = game.get("startTimeUTC")
    if not raw:
        return slate, None
    utc = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    et = utc.astimezone(EASTERN)
    return et.date(), et.replace(tzinfo=None)


def slate_game_dates_et(games: list[dict], slate_date: date | None = None) -> set[date]:
    """All ET calendar dates represented in the current schedule slice."""
    slate = slate_date or now_eastern().date()
    dates = {slate}
    for game in games:
        d, _ = game_datetime_et(game, slate)
        dates.add(d)
    return dates
