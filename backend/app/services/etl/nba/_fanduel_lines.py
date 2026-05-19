"""Sync Odds API helpers for NBA player-prop lines (FanDuel via The Odds API).

Port of YetiBets ``utilities/utilities_functions.get_event_id_for_game`` and
``get_fanduel_line``. Used by projection ETL tasks when ``ODDS_API_KEY`` is set.
"""

from __future__ import annotations

import logging
from typing import Tuple

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4/sports"


def get_event_id_for_game(sport: str, team1: str, team2: str) -> str | None:
    api_key = settings.ODDS_API_KEY
    if not api_key:
        return None
    try:
        resp = requests.get(
            f"{_BASE_URL}/{sport}/events",
            params={"apiKey": api_key},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.debug("Odds API events %s: HTTP %s", sport, resp.status_code)
            return None
        for event in resp.json():
            home = event.get("home_team")
            away = event.get("away_team")
            if {home, away} == {team1, team2}:
                return event.get("id")
    except Exception as exc:
        logger.debug("get_event_id_for_game failed: %s", exc)
    return None


def get_fanduel_line(
    sport: str,
    event_id: str,
    player_name: str,
    market: str,
    projection: float,
) -> Tuple[float, float, str]:
    """Return (line, american_price, 'o'|'u'|'n') for a player prop market."""
    api_key = settings.ODDS_API_KEY
    if not api_key:
        return 0.0, 0.0, "n"
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
            return 0.0, 0.0, "n"
        data = resp.json()
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
