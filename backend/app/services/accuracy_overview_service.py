"""Cross-league season (or rolling) accuracy summaries for the Stat Projections hub."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

WindowMode = Literal["season", "last_30"]


def window_date_bounds(
    *, sport: str, mode: WindowMode, today: date
) -> tuple[date, date]:
    """Return [start, end] inclusive for aggregation (end is always `today`)."""
    end = today
    if mode == "last_30":
        return today - timedelta(days=30), end
    if sport == "mlb":
        start = date(today.year, 3, 15)
        if today < start:
            start = date(today.year - 1, 3, 15)
        return start, end
    if sport in ("nba", "nhl"):
        start = date(today.year, 10, 1)
        if today < start:
            start = date(today.year - 1, 10, 1)
        return start, end
    if sport == "nfl":
        start = date(today.year, 9, 1)
        if today < start:
            start = date(today.year - 1, 9, 1)
        return start, end
    if sport == "wnba":
        start = date(today.year, 5, 1)
        if today < start:
            start = date(today.year - 1, 5, 1)
        return start, end
    raise ValueError(f"unknown sport: {sport}")


def build_accuracy_overview(
    db: Session,
    *,
    window: WindowMode = "season",
    today: date | None = None,
) -> dict[str, Any]:
    """One combined graded-accuracy line per league (fixed order)."""
    from datetime import date as date_cls

    from app.services import (
        mlb_accuracy_service,
        nba_accuracy_service,
        nfl_accuracy_service,
        nhl_accuracy_service,
        wnba_accuracy_service,
    )

    as_of = today or date_cls.today()
    loaders = [
        ("mlb", mlb_accuracy_service),
        ("nba", nba_accuracy_service),
        ("wnba", wnba_accuracy_service),
        ("nfl", nfl_accuracy_service),
        ("nhl", nhl_accuracy_service),
    ]
    items: list[dict[str, Any]] = []
    for sport, mod in loaders:
        start, end = window_date_bounds(sport=sport, mode=window, today=as_of)
        items.append(mod.season_overview(db, start=start, end=end))
    return {
        "window": window,
        "as_of": as_of.isoformat(),
        "items": items,
    }
