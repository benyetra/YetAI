"""Odds API credit report: bill-based run-out projection next to the recorded counter.

The counter (odds_api_budget) only sees this codebase; another consumer of the same
key is invisible to it. The bill is `x-requests-remaining` from the free quota call,
so we snapshot it per UTC day and project run-out from that.
"""

from __future__ import annotations

import calendar
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.services import odds_api_budget as budget

log = logging.getLogger(__name__)

_QUOTA_KEY = "odds:quota:remaining"
_QUOTA_FIRST_KEY = "odds:quota:remaining_first"
_TTL_SECONDS = 40 * 86400
RESERVE_FRACTION = 0.05
RATE_DAYS = 7


def cycle_credits() -> int:
    return int(os.getenv("ODDS_API_CYCLE_CREDITS", "100000"))


def cycle_start() -> date:
    return date.fromisoformat(os.getenv("ODDS_API_CYCLE_START", "2026-11-14"))


def _add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def next_reset(today: date, start: Optional[date] = None) -> date:
    """First `start + k months` (k >= 0) strictly after today."""
    start = start or cycle_start()
    k = 0
    while _add_months(start, k) <= today:
        k += 1
    return _add_months(start, k)


def snapshot_quota(q: dict, day: str) -> None:
    """Store today's latest reading and (NX) the first reading of the UTC day."""
    client = budget._sync_redis()
    if not client:
        return
    try:
        val = int(q["remaining"])
        client.set(f"{_QUOTA_KEY}:{day}", val, ex=_TTL_SECONDS)
        client.set(f"{_QUOTA_FIRST_KEY}:{day}", val, ex=_TTL_SECONDS, nx=True)
    except Exception as exc:
        log.warning("odds quota snapshot failed: %s", exc)
        budget._reset_client()


def _first(day: date) -> Optional[int]:
    client = budget._sync_redis()
    if not client:
        return None
    try:
        v = client.get(f"{_QUOTA_FIRST_KEY}:{day.isoformat()}")
        return int(v) if v is not None else None
    except Exception:
        return None


def _rate(today: date) -> tuple[Optional[float], str]:
    end = _first(today)
    if end is not None:
        for n in range(RATE_DAYS, 0, -1):  # widest window with a snapshot
            start = _first(today - timedelta(days=n))
            if start is not None and start - end > 0:  # <= 0 means a cycle reset
                return (start - end) / n, "bill"
    used = [
        budget.get_daily_usage_sync((today - timedelta(days=n)).isoformat())
        for n in range(1, RATE_DAYS + 1)
    ]
    return sum(used) / RATE_DAYS, "counter"


def credits_summary(today: date, quota: Optional[dict]) -> dict:
    y = today - timedelta(days=1)
    reset = next_reset(today)
    days_to_reset = (reset - today).days
    remaining = int(quota["remaining"]) if quota else None
    by_group = budget.get_usage_by_group_sync(y.isoformat())
    recorded = budget.get_daily_usage_sync(y.isoformat())
    first_y, first_t = _first(y), _first(today)
    billed = first_y - first_t if first_y is not None and first_t is not None else None
    rate, source = _rate(today)
    runout = None
    if remaining is not None and rate:
        runout = today + timedelta(days=int(remaining / rate))
    reserve = int(cycle_credits() * RESERVE_FRACTION)
    return {
        "remaining": remaining,
        "cycle_start": cycle_start().isoformat(),
        "next_reset": reset.isoformat(),
        "days_to_reset": days_to_reset,
        "yesterday_recorded": recorded,
        "yesterday_by_group": dict(
            sorted(by_group.items(), key=lambda kv: kv[1], reverse=True)
        ),
        "yesterday_billed": billed,
        "yesterday_unrecorded": None if billed is None else billed - recorded,
        "rate_7d": rate,
        "rate_source": source,
        "projected_runout": runout.isoformat() if runout else None,
        "runs_out_before_reset": bool(runout and runout < reset),
        "budget": budget.DAILY_CREDIT_BUDGET,
        "recommended_daily": (
            None
            if remaining is None
            else max(0, (remaining - reserve) // days_to_reset)
        ),
    }


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
