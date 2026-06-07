"""Sync HTTP helpers for ETL code paths that call The Odds API via requests."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from app.services.odds_api_budget import guard_sync, record_sync

logger = logging.getLogger(__name__)


def sync_odds_get(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    caller: str = "sync",
    estimated_cost: int = 1,
    timeout: int = 30,
    raise_for_status: bool = True,
) -> Optional[requests.Response]:
    """GET with daily budget guard and usage accounting."""
    if not guard_sync(caller, estimated_cost=estimated_cost):
        return None
    try:
        resp = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning(
            "Odds API sync GET failed caller=%s url=%s: %s", caller, url, exc
        )
        return None
    if resp.ok:
        record_sync(int(resp.headers.get("x-requests-last", 1) or 1), caller)
    if raise_for_status and not resp.ok:
        resp.raise_for_status()
    return resp
