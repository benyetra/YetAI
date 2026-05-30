"""Sync Odds API helpers for NBA player-prop lines (FanDuel via The Odds API).

Port of YetiBets ``utilities/utilities_functions.get_event_id_for_game`` and
``get_fanduel_line``. Used by projection ETL tasks when ``ODDS_API_KEY`` is set.

The Odds API returns *all* players for a market in a single event-odds response,
but the projection ETL looks each player up individually. To avoid spending one
Odds API credit per player, we memoize the per-sport events list and each
``(sport, event_id, market)`` odds payload for a short TTL. Within one ETL run
every player lookup for the same (game, market) reuses one HTTP response, while
the short TTL guarantees the next scheduled run pulls fresh lines.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Tuple

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4/sports"

# A single ETL pipeline run completes well within this window, so all player
# lookups for the same (game, market) reuse one HTTP response. The next
# scheduled run (hours later) misses the cache and pulls fresh lines.
_CACHE_TTL_SECONDS = 600

# key -> (expires_at_monotonic, value)
_cache: dict[Any, Tuple[float, Any]] = {}


def _cache_get(key: Any) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() >= expires_at:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: Any, value: Any) -> None:
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)


def clear_cache() -> None:
    """Drop all memoized Odds API responses (used by tests / run boundaries)."""
    _cache.clear()


def _get_events(sport: str) -> list[dict]:
    """Return the Odds API events list for ``sport`` (memoized per run)."""
    cache_key = ("events", sport)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    api_key = settings.ODDS_API_KEY
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"{_BASE_URL}/{sport}/events",
            params={"apiKey": api_key},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.debug("Odds API events %s: HTTP %s", sport, resp.status_code)
            return []
        events = resp.json() or []
        _cache_set(cache_key, events)
        return events
    except Exception as exc:
        logger.debug("get_events failed: %s", exc)
        return []


def get_event_id_for_game(sport: str, team1: str, team2: str) -> str | None:
    for event in _get_events(sport):
        home = event.get("home_team")
        away = event.get("away_team")
        if {home, away} == {team1, team2}:
            return event.get("id")
    return None


def _get_event_market_odds(sport: str, event_id: str, market: str) -> dict:
    """Return the FanDuel event-odds payload for one market (memoized per run)."""
    cache_key = ("odds", sport, event_id, market)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    api_key = settings.ODDS_API_KEY
    if not api_key:
        return {}
    try:
        resp = requests.get(
            f"{_BASE_URL}/{sport}/events/{event_id}/odds",
            params={
                "regions": "us",
                "oddsFormat": "american",
                "apiKey": api_key,
                "markets": market,
                "bookmakers": "fanduel",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json() or {}
        _cache_set(cache_key, data)
        return data
    except Exception as exc:
        logger.debug("get_event_market_odds %s/%s: %s", event_id, market, exc)
        return {}


def get_fanduel_line(
    sport: str,
    event_id: str,
    player_name: str,
    market: str,
    projection: float,
) -> Tuple[float, float, str]:
    """Return (line, american_price, 'o'|'u'|'n') for a player prop market."""
    data = _get_event_market_odds(sport, event_id, market)
    if not data:
        return 0.0, 0.0, "n"
    try:
        for bookmaker in data.get("bookmakers", []):
            if bookmaker.get("title") != "FanDuel":
                continue
            for mkt in bookmaker.get("markets", []):
                if mkt.get("key") != market:
                    continue
                over_outcome = None
                under_outcome = None
                for outcome in mkt.get("outcomes", []):
                    if outcome.get("description") != player_name:
                        continue
                    if outcome.get("name") == "Over":
                        over_outcome = outcome
                    elif outcome.get("name") == "Under":
                        under_outcome = outcome
                if over_outcome and under_outcome:
                    over_point = float(over_outcome["point"])
                    if projection < over_point - 1.5:
                        return (
                            float(under_outcome["point"]),
                            float(under_outcome["price"]),
                            "u",
                        )
                    return (
                        float(over_outcome["point"]),
                        float(over_outcome["price"]),
                        "o",
                    )
    except Exception as exc:
        logger.debug("get_fanduel_line for %s: %s", player_name, exc)
    return 0.0, 0.0, "n"


NBA_SPORT = "basketball_nba"

# Odds API market keys for core player props (FanDuel bookmaker).
PROP_MARKETS: dict[str, str] = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "three_pt_made": "player_threes",
    "pra": "player_points_rebounds_assists",
}


def fetch_fanduel_prop_for_player(
    team_name: str,
    opponent_team_name: str,
    player_name: str,
    market: str,
    projection: float,
) -> tuple[float | None, str | None]:
    """Resolve FanDuel line + pick side for one player prop, or (None, None)."""
    event_id = get_event_id_for_game(NBA_SPORT, team_name, opponent_team_name)
    if not event_id:
        return None, None
    line, _price, flag = get_fanduel_line(
        NBA_SPORT, event_id, player_name, market, projection
    )
    if line <= 0 or flag == "n":
        return None, None
    return line, flag


def apply_fanduel_to_projection(
    row: Any,
    *,
    team_name: str,
    opponent_team_name: str,
    player_name: str,
    market: str,
    projection: float,
) -> bool:
    """Set ``fanduel_line`` / ``fanduel_over_under`` on a projection ORM row.

    Returns True when a line was stored.
    """
    line, flag = fetch_fanduel_prop_for_player(
        team_name, opponent_team_name, player_name, market, projection
    )
    row.fanduel_line = line
    row.fanduel_over_under = flag
    return line is not None
