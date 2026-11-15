"""
Shared Odds API daily credit budget (Redis-backed).

Every outbound Odds API call goes through app/services/odds_api_sync.py
(`sync_odds_get` / `async_odds_get`), which guards and records here. The sync
and async styles share ONE counter: the async functions run the sync ones in a
thread, so both land on the same Redis key (`pick_redis_url()`), never on a
per-process in-memory fallback.

Recorded cost is the `x-requests-last` header as sent (free calls record 0), so
the counter equals the bill. A per-day hash breaks usage down by caller group.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DAILY_CREDIT_BUDGET = int(os.getenv("ODDS_API_DAILY_BUDGET", "500"))
_BUDGET_KEY_PREFIX = "odds:budget:credits"
_CALLERS_KEY_PREFIX = "odds:budget:callers"
_TTL_SECONDS = 35 * 86400  # the review needs 8 days of history

_client = None
# Once-per-process-per-UTC-day log flags: {"refusal": day, "dead": day}
_logged_day: dict[str, str] = {}


class OddsApiBudgetExceeded(Exception):
    """Raised when the UTC-day credit budget is exhausted."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _budget_key(day: Optional[str] = None) -> str:
    return f"{_BUDGET_KEY_PREFIX}:{day or _today()}"


def _callers_key(day: Optional[str] = None) -> str:
    return f"{_CALLERS_KEY_PREFIX}:{day or _today()}"


def _log_once(flag: str, level: int, msg: str, *args) -> None:
    day = _today()
    if _logged_day.get(flag) == day:
        logger.debug(msg, *args)
        return
    _logged_day[flag] = day
    logger.log(level, msg, *args)


_HEX = re.compile(r"[0-9a-f]{8,}")


def caller_group(caller: str) -> str:
    """Stable short group for reporting: `etl.nba`, `api.odds`, `games_sync`..."""
    s = (caller or "").strip().lower()
    if not s or s == "unknown":
        return "unknown"
    s = s.split("/events", 1)[0]  # `sport/events/<id>/odds` -> `sport`
    parts = [p for p in s.split(".") if p and not _HEX.fullmatch(p)]
    if not parts:
        return "unknown"
    n = 2 if parts[0] in ("etl", "api") else 1
    return ".".join(parts[:n])


def _sync_redis():
    """Cached sync Redis client; recreated after an error (see `_reset_client`)."""
    global _client
    if _client is not None:
        return _client
    try:
        import redis
        from app.core.redis_broker import pick_redis_url

        _client = redis.from_url(
            pick_redis_url(),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        return _client
    except Exception as exc:
        logger.debug("Odds budget sync Redis unavailable: %s", exc)
        return None


def _reset_client() -> None:
    global _client
    _client = None


def _usage(day: Optional[str] = None) -> Optional[int]:
    """Credits used on `day`, or None when Redis is unreachable."""
    client = _sync_redis()
    if not client:
        return None
    try:
        val = client.get(_budget_key(day))
        return int(val) if val else 0
    except Exception as exc:
        logger.debug("Odds budget read failed: %s", exc)
        _reset_client()
        return None


def get_daily_usage_sync(day: Optional[str] = None) -> int:
    return _usage(day) or 0


def get_usage_by_group_sync(day: str) -> dict[str, int]:
    client = _sync_redis()
    if not client:
        return {}
    try:
        return {k: int(v) for k, v in client.hgetall(_callers_key(day)).items()}
    except Exception as exc:
        logger.debug("Odds budget group read failed: %s", exc)
        _reset_client()
        return {}


def guard_sync(caller: str, estimated_cost: int = 1) -> bool:
    """Return False when the daily budget would be exceeded.

    Fails open (usage reads as 0) when Redis is unreachable, logging that once.
    """
    used = _usage()
    if used is None:
        _log_once(
            "dead",
            logging.WARNING,
            "Odds API budget counter unreachable (Redis); calls are NOT being "
            "capped or counted until it recovers",
        )
        used = 0
    if used + max(int(estimated_cost or 0), 1) > DAILY_CREDIT_BUDGET:
        _log_once(
            "refusal",
            logging.WARNING,
            "Odds API daily budget reached (%s/%s); refusing further calls "
            "today; callers fall back to cached data",
            used,
            DAILY_CREDIT_BUDGET,
        )
        logger.debug("Odds API budget refused caller=%s", caller)
        return False
    return True


def record_sync(cost: int, caller: str = "unknown") -> int:
    """Add `cost` (header value as given; 0 allowed) to today's usage."""
    try:
        cost = max(int(cost), 0)
    except (TypeError, ValueError):
        cost = 0
    client = _sync_redis()
    if not client:
        return cost
    key, ckey = _budget_key(), _callers_key()
    try:
        pipe = client.pipeline()
        pipe.incrby(key, cost)
        pipe.expire(key, _TTL_SECONDS)
        pipe.hincrby(ckey, caller_group(caller), cost)
        pipe.expire(ckey, _TTL_SECONDS)
        new_total = pipe.execute()[0]
        logger.info(
            "Odds API budget caller=%s cost=%s day_total=%s/%s",
            caller,
            cost,
            new_total,
            DAILY_CREDIT_BUDGET,
        )
        return int(new_total)
    except Exception as exc:
        logger.warning("Odds API budget record failed: %s", exc)
        _reset_client()
        return cost


async def get_daily_usage_async() -> int:
    return await asyncio.to_thread(get_daily_usage_sync)


async def guard_async(caller: str, estimated_cost: int = 1) -> bool:
    return await asyncio.to_thread(guard_sync, caller, estimated_cost)


async def record_async(cost: int, caller: str = "unknown") -> int:
    return await asyncio.to_thread(record_sync, cost, caller)
