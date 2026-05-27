"""Historical MLB odds via The Odds API (cached per date for backtests)."""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import requests

from app.services.etl.mlb._enrichment_helpers import (
    extract_h2h_prices,
    find_event_for_game,
    teams_match,
)
from app.services.etl.mlb.backtest.cache import cached_api_call, get_cached

logger = logging.getLogger(__name__)

# 10 credits × 1 region × 2 markets (h2h, totals) per date
CREDITS_PER_DATE = 20

PREFERRED_BOOKMAKERS = ("fanduel", "draftkings", "betmgm")

HISTORICAL_ODDS_URL = (
    "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds/"
)


def resolve_odds_api_key() -> str | None:
    """ODDS_API_KEY from env or app settings (after dotenv load)."""
    key = (os.getenv("ODDS_API_KEY") or os.getenv("ODDS_API") or "").strip()
    if key and key not in ("your_odds_api_key_here", "your-odds-api-key"):
        return key
    try:
        from app.core.config import settings

        key = (settings.ODDS_API_KEY or "").strip()
        if key and key not in ("your_odds_api_key_here", "your-odds-api-key"):
            return key
    except Exception:
        pass
    return None


def _extract_totals_prices(
    event: dict[str, Any],
    preferred_bookmakers: tuple[str, ...] = PREFERRED_BOOKMAKERS,
) -> dict[str, Any]:
    for bm in event.get("bookmakers", []):
        if bm.get("key") not in preferred_bookmakers:
            continue
        for market in bm.get("markets", []):
            if market.get("key") != "totals":
                continue
            out: dict[str, Any] = {}
            for o in market.get("outcomes", []):
                name = o.get("name")
                if name == "Over":
                    out["point"] = o.get("point")
                    out["over"] = o.get("price")
                elif name == "Under":
                    out["under"] = o.get("price")
            if out:
                return out
    return {}


def fetch_historical_odds_snapshot(
    game_date: date,
    *,
    api_key: str | None = None,
    cache_only: bool = False,
) -> dict[str, Any] | None:
    """One Odds API historical call for all MLB games on a calendar day."""
    key = api_key or resolve_odds_api_key()
    if not key:
        logger.warning("ODDS_API_KEY not set; skip historical odds")
        return None

    params_cache = {"date": game_date.isoformat()}

    def _fetch():
        try:
            resp = requests.get(
                HISTORICAL_ODDS_URL,
                params={
                    "apiKey": key,
                    "regions": "us",
                    "markets": "h2h,totals",
                    "date": f"{game_date.isoformat()}T17:00:00Z",
                },
                timeout=30,
            )
            remaining = resp.headers.get("x-requests-remaining")
            used = resp.headers.get("x-requests-used")
            cost = resp.headers.get("x-requests-last")
            if resp.status_code != 200:
                logger.warning(
                    "Historical odds %s: HTTP %s — %s",
                    game_date,
                    resp.status_code,
                    (resp.text or "")[:200],
                )
                return None
            payload = resp.json()
            logger.info(
                "Historical odds %s: cached snapshot (cost=%s, remaining=%s, used=%s)",
                game_date,
                cost,
                remaining,
                used,
            )
            return payload
        except Exception as exc:
            logger.warning("Historical odds %s failed: %s", game_date, exc)
            return None

    return cached_api_call(
        "historical_odds",
        params_cache,
        _fetch,
        cache_only=cache_only,
    )


def match_game_odds(
    game_date: date,
    home_name: str,
    away_name: str,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Find h2h + totals for one game from a daily historical snapshot."""
    if not snapshot:
        return {}

    events = snapshot.get("data", [])
    if not isinstance(events, list):
        return {}

    game_row = {"home_name": home_name, "away_name": away_name}
    event = find_event_for_game(game_row, events)
    if not event:
        return {}

    h2h = extract_h2h_prices(event, PREFERRED_BOOKMAKERS)
    totals = _extract_totals_prices(event)
    if not h2h and not totals:
        return {}

    return {"h2h": h2h, "totals": totals}


def is_date_cached(game_date: date) -> bool:
    return get_cached("historical_odds", {"date": game_date.isoformat()}) is not None
