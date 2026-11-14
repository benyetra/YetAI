"""Nightly grading lookback shared by every sport's actuals jobs.

Graders used to look only at yesterday, so one failed night (API outage,
crashed worker) was never graded. Each job instead re-grades the last few
Eastern days with upserts, so a missed night heals on the next run. Older
days are almost all already-graded rows, so the default window is short;
``<SPORT>_GRADING_LOOKBACK_DAYS`` widens it for a catch-up.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DEFAULT_GRADING_LOOKBACK_DAYS = 3


def eastern_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def grading_lookback_days(
    sport: str, default: int = DEFAULT_GRADING_LOOKBACK_DAYS
) -> int:
    """Days re-graded each night, yesterday included (env ``<SPORT>_GRADING_LOOKBACK_DAYS``)."""
    name = f"{sport.upper()}_GRADING_LOOKBACK_DAYS"
    raw = os.getenv(name, "").strip()
    try:
        return max(1, int(raw)) if raw else default
    except ValueError:
        logger.warning("Bad %s=%r; using default %s", name, raw, default)
        return default


def grading_dates(
    sport: str,
    *,
    today: date | None = None,
    default: int = DEFAULT_GRADING_LOOKBACK_DAYS,
) -> list[date]:
    """Eastern dates to grade tonight, oldest first, ending yesterday."""
    end = (today or eastern_today()) - timedelta(days=1)
    n = grading_lookback_days(sport, default)
    return [end - timedelta(days=i) for i in range(n - 1, -1, -1)]
