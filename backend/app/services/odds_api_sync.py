"""The only place that talks HTTP to The Odds API (sync and async paths).

Both paths guard the shared daily budget first and record the `x-requests-last`
header cost on every response that carries it. tests/test_odds_api_guard_scan.py
fails if any other module calls the API directly.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from app.services.odds_api_budget import (
    guard_async,
    guard_sync,
    record_async,
    record_sync,
)

logger = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
QUOTA_URL = f"{ODDS_API_BASE}/sports/"


def _header_cost(headers, ok: bool, estimated_cost: int):
    """Header cost as sent (0 allowed); no header: estimate for ok responses."""
    raw = {str(k).lower(): v for k, v in headers.items()}.get("x-requests-last")
    if raw is None or raw == "":
        return estimated_cost if ok else 0
    return raw


def sync_odds_get(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    caller: str = "sync",
    estimated_cost: int = 1,
    timeout: int = 30,
    raise_for_status: bool = True,
    enforce_budget: bool = True,
    snapshot: bool = True,
) -> Optional[requests.Response]:
    """GET with daily budget guard and usage accounting.

    enforce_budget=False records the cost but never refuses (explicit backfills).
    snapshot=False skips the odds_snapshots hook (historical endpoints).
    """
    allowed = guard_sync(caller, estimated_cost=estimated_cost)
    if not allowed and enforce_budget:
        return None
    try:
        resp = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning(
            "Odds API sync GET failed caller=%s url=%s: %s", caller, url, exc
        )
        return None
    ok = resp.status_code < 400
    record_sync(_header_cost(resp.headers, ok, estimated_cost), caller)
    if ok and snapshot:
        _snapshot(url, params, resp)
    if raise_for_status and not ok:
        resp.raise_for_status()
    return resp


async def async_odds_get(
    session,
    url: str,
    *,
    params: Optional[dict] = None,
    caller: str = "async",
    estimated_cost: int = 1,
    timeout: int = 30,
) -> Optional[tuple[int, dict, Any]]:
    """Guarded aiohttp GET -> (status, headers, parsed JSON or None).

    Returns None when the budget refuses or the network fails. No snapshot hook.
    """
    import aiohttp

    if not await guard_async(caller, estimated_cost):
        return None
    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            headers = dict(response.headers)
            body = None
            try:
                body = await response.json(content_type=None)
            except Exception:
                pass
            status = response.status
    except (aiohttp.ClientError, TimeoutError) as exc:
        logger.warning(
            "Odds API async GET failed caller=%s url=%s: %s", caller, url, exc
        )
        return None
    await record_async(_header_cost(headers, status < 400, estimated_cost), caller)
    return status, headers, body


def read_live_quota() -> Optional[dict]:
    """Free call (/sports costs 0): the account's remaining/used credits."""
    key = os.getenv("ODDS_API_KEY")
    if not key:
        from app.core.config import settings

        key = settings.ODDS_API_KEY
    resp = sync_odds_get(
        QUOTA_URL,
        params={"apiKey": key},
        caller="quota.read",
        estimated_cost=0,
        snapshot=False,
        raise_for_status=False,
    )
    if resp is None or resp.status_code >= 400:
        return None
    try:
        return {
            "remaining": int(resp.headers["x-requests-remaining"]),
            "used": int(resp.headers["x-requests-used"]),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    except (KeyError, ValueError):
        return None


def _snapshot(url: str, params: Optional[dict], resp: requests.Response) -> None:
    """Keep every book's quote from an odds payload (app/services/odds_snapshots.py)."""
    try:
        data = resp.json()
    except ValueError:
        return
    from app.services.odds_snapshots import record_response

    record_response(url, params, data)
