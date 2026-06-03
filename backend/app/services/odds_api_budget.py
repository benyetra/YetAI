"""
Shared Odds API daily credit budget (Redis-backed).

All outbound the-odds-api.com calls — async (OddsAPIService) and sync (ETL
requests.get) — must pass through this guard so multiple API workers cannot
each burn quota independently when in-memory odds caches miss.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DAILY_CREDIT_BUDGET = int(os.getenv("ODDS_API_DAILY_BUDGET", "250"))
_BUDGET_KEY_PREFIX = "odds:budget:credits"


class OddsApiBudgetExceeded(Exception):
    """Raised when the UTC-day credit budget is exhausted."""


def _budget_key(day: Optional[str] = None) -> str:
    d = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{_BUDGET_KEY_PREFIX}:{d}"


def _sync_redis():
    """Best-effort sync Redis client for Celery / ETL threads."""
    try:
        import redis
        from app.core.redis_broker import pick_redis_url

        return redis.from_url(
            pick_redis_url(),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    except Exception as exc:
        logger.debug("Odds budget sync Redis unavailable: %s", exc)
        return None


def get_daily_usage_sync() -> int:
    client = _sync_redis()
    if not client:
        return 0
    try:
        val = client.get(_budget_key())
        return int(val) if val else 0
    except Exception:
        return 0


def guard_sync(caller: str, estimated_cost: int = 1) -> bool:
    """Return False when the daily budget would be exceeded."""
    used = get_daily_usage_sync()
    if used + max(estimated_cost, 1) > DAILY_CREDIT_BUDGET:
        logger.warning(
            "Odds API budget blocked caller=%s used=%s budget=%s",
            caller,
            used,
            DAILY_CREDIT_BUDGET,
        )
        return False
    return True


def record_sync(cost: int, caller: str = "unknown") -> int:
    """Increment UTC-day usage after a completed Odds API call."""
    cost = max(int(cost or 1), 1)
    client = _sync_redis()
    if not client:
        return cost
    key = _budget_key()
    try:
        pipe = client.pipeline()
        pipe.incrby(key, cost)
        pipe.expire(key, 172800)  # 48h TTL
        new_total, _ = pipe.execute()
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
        return cost


async def get_daily_usage_async() -> int:
    from app.services.cache_service import cache_service

    val = await cache_service.get_int(_budget_key())
    return val or 0


async def guard_async(caller: str, estimated_cost: int = 1) -> bool:
    used = await get_daily_usage_async()
    if used + max(estimated_cost, 1) > DAILY_CREDIT_BUDGET:
        logger.warning(
            "Odds API budget blocked caller=%s used=%s budget=%s",
            caller,
            used,
            DAILY_CREDIT_BUDGET,
        )
        return False
    return True


async def record_async(cost: int, caller: str = "unknown") -> int:
    from app.services.cache_service import cache_service

    cost = max(int(cost or 1), 1)
    new_total = await cache_service.incrby(_budget_key(), cost, expire_seconds=172800)
    logger.info(
        "Odds API budget caller=%s cost=%s day_total=%s/%s",
        caller,
        cost,
        new_total,
        DAILY_CREDIT_BUDGET,
    )
    return new_total
