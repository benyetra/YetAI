"""When a projection row stops changing: shared by every sport's ETL writers.

A row, its market line and its pick are what users saw before the game. Once
the game has started they are what the pick is graded on, so line updaters,
projectors, prop generators, stale-row deletes and upserts leave a started
game alone. Before the start a refresh may update a row, but a book that has
no market right now is not a reason to drop the line we already had.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


def has_started(
    start: datetime | date | None,
    *,
    game_date: date | None = None,
    now: datetime | None = None,
    naive_tz=UTC,
) -> bool:
    """True once a game's start has passed.

    ``start`` is the scheduled start; a naive value is read in ``naive_tz``
    (pass ``EASTERN`` for naive Eastern columns). A bare date, or no start at
    all with a ``game_date``, counts as started from the following Eastern
    day: an unknown start keeps today's pre-game board fresh but never lets a
    game on a past ET date be rewritten. Nothing known -> False.
    ``now`` is aware, or naive in ``naive_tz``; default is the current time.
    """
    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=naive_tz)
    if isinstance(start, datetime):
        if start.tzinfo is None:
            start = start.replace(tzinfo=naive_tz)
        return start <= current
    day = start if start is not None else game_date
    if isinstance(day, datetime):
        day = day.date()
    if day is None:
        return False
    return day < current.astimezone(EASTERN).date()


def keep_known(row: Any, values: dict[str, Any]) -> None:
    """Set ``values`` on an ORM row, except None over a value already stored.

    A refresh that finds no market for a game must not wipe the line (or
    price) an earlier run stored.
    """
    for key, value in values.items():
        if value is None and getattr(row, key, None) is not None:
            continue
        setattr(row, key, value)


def not_started(
    items: Iterable[Any], start_of, *, now: datetime | None = None, naive_tz=UTC
) -> list[Any]:
    """``items`` whose game has not started; ``start_of(item)`` returns
    ``(start, game_date)``."""
    kept = []
    for item in items:
        start, game_day = start_of(item)
        if not has_started(start, game_date=game_day, now=now, naive_tz=naive_tz):
            kept.append(item)
    return kept
