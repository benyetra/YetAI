"""Shared API-Sports NBA v2 client + player-ID resolver.

Two pieces of cross-script behavior live here so each ETL service file stays
focused on its own table/logic:

- `api_request(endpoint, params)` — naive 3-attempt retry against
  https://v2.nba.api-sports.io, with 60s backoff on 429s.
- `resolve_nba_player_id(name, static_players=None)` — match player name to an
  NBA.com player_id via nba_api's static list + MANUAL_PLAYER_IDS override for
  draftees the static list lacks.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests
from nba_api.stats.static import players as nba_players  # type: ignore

logger = logging.getLogger(__name__)

API_BASE_URL = "https://v2.nba.api-sports.io"
API_KEY_ENV = "NBA_API_KEY"


def get_current_season() -> int:
    """NBA league year starts in October."""
    from datetime import datetime

    now = datetime.now()
    return now.year if now.month >= 10 else now.year - 1


# API-Sports team_id → NBA.com team_id. Embedded from YetiBets
# scripts/nba/team_id_mapping.json (30 NBA teams; ids 31 and 37 both map to
# the Spurs in source data — preserved as-is).
API_SPORTS_TO_NBA: dict[int, int] = {
    1: 1610612737,
    2: 1610612738,
    4: 1610612751,
    5: 1610612766,
    6: 1610612741,
    7: 1610612739,
    8: 1610612742,
    9: 1610612743,
    10: 1610612765,
    11: 1610612744,
    14: 1610612745,
    15: 1610612754,
    16: 1610612746,
    17: 1610612747,
    19: 1610612763,
    20: 1610612748,
    21: 1610612749,
    22: 1610612750,
    23: 1610612740,
    24: 1610612752,
    25: 1610612760,
    26: 1610612753,
    27: 1610612755,
    28: 1610612756,
    29: 1610612757,
    30: 1610612758,
    31: 1610612759,
    37: 1610612759,
    38: 1610612761,
    40: 1610612762,
    41: 1610612764,
}

# Players missing from nba_api's static list — usually recent draftees.
MANUAL_PLAYER_IDS: dict[str, int] = {
    "nikola jokic": 203999,
    "victor wembanyama": 1641705,
    "chet holmgren": 1631096,
    "scoot henderson": 1641706,
    "jaime jaquez jr": 1641707,
    "amen thompson": 1641708,
    "ausar thompson": 1641709,
    "brandon miller": 1641710,
    "gradey dick": 1641711,
    "cam whitmore": 1631170,
    "keyonte george": 1641712,
    "bilal coulibaly": 1641713,
    "dereck lively ii": 1641714,
    "jordan hawkins": 1641715,
    "jett howard": 1641716,
    "taylor hendricks": 1641717,
    "kobe bufkin": 1641718,
}


def api_request(endpoint: str, params: dict | None = None) -> dict | None:
    """GET against v2.nba.api-sports.io with simple retry. Returns parsed JSON
    or None after exhausting attempts."""
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} env var is required")
    url = f"{API_BASE_URL}/{endpoint}"
    headers = {"x-apisports-key": api_key}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                logger.warning("api-sports rate-limited, sleeping 60s")
                time.sleep(60)
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning(
                "api-sports %s failed (attempt %d/3): %s", endpoint, attempt + 1, exc
            )
            if attempt < 2:
                time.sleep(5)
    return None


_STATIC_PLAYERS_CACHE: list[dict] | None = None


def _get_static_players() -> list[dict]:
    """Cache nba_api.static.players.get_players() across calls."""
    global _STATIC_PLAYERS_CACHE
    if _STATIC_PLAYERS_CACHE is None:
        _STATIC_PLAYERS_CACHE = nba_players.get_players()
    return _STATIC_PLAYERS_CACHE


def resolve_nba_player_id(
    player_name: str, static_players: list[dict] | None = None
) -> Optional[int]:
    """Match a player name to an NBA.com player_id.

    Order:
      1. MANUAL_PLAYER_IDS (lowercase exact match)
      2. nba_api static list — exact name match (case-insensitive)
      3. nba_api static list — substring match either direction
    """
    search = (player_name or "").lower().strip()
    if not search:
        return None
    if search in MANUAL_PLAYER_IDS:
        return MANUAL_PLAYER_IDS[search]
    if static_players is None:
        static_players = _get_static_players()
    for p in static_players:
        if p["full_name"].lower() == search:
            return p["id"]
    for p in static_players:
        full = p["full_name"].lower()
        if search in full or full in search:
            return p["id"]
    return None
