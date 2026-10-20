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
import re
import time
import unicodedata
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

# Pins for players nba_api's static list lacks (or names it can't match).
# Every id here MUST be the player's real NBA.com PERSON_ID: a wrong id files
# that player's box scores under someone else (see
# tests/test_nba_player_id_resolver.py, which checks entries against
# nba_api). Keys are normalized with `normalize_player_name`.
MANUAL_PLAYER_IDS: dict[str, int] = {
    "victor wembanyama": 1641705,
    "chet holmgren": 1631096,
    "amen thompson": 1641708,
    "ausar thompson": 1641709,
    "gradey dick": 1641711,
}

# Players with no NBA.com id we can resolve (mostly rookies newer than the
# pinned nba_api release; NBA.com blocks cloud IPs, so no live lookup) get a
# stable synthetic id derived from their API-Sports id. NBA.com ids are
# < 2M, so this range never collides. Pin the real id in MANUAL_PLAYER_IDS
# once known — the synthetic id's history does not carry over.
SYNTHETIC_ID_BASE = 900_000_000


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


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_player_name(name: str | None, strip_suffix: bool = True) -> str:
    """Accent-, case-, punctuation- and suffix-insensitive name key.

    "Luka Dončić" / "Luka Doncic" -> "luka doncic";
    "Jaime Jaquez Jr." -> "jaime jaquez"; "Ja'Kobi Gillespie" -> "jakobi gillespie".
    """
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[.'’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = text.split()
    while strip_suffix and len(tokens) > 2 and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


_NameIndex = dict[str, list[dict]]
_NAME_INDEX_CACHE: tuple[list[dict], _NameIndex, _NameIndex] | None = None


def _name_indexes(static_players: list[dict]) -> tuple[_NameIndex, _NameIndex]:
    """(with-suffix, suffix-stripped) normalized name -> players, cached for
    the (cached) static list."""
    global _NAME_INDEX_CACHE
    if _NAME_INDEX_CACHE is not None and _NAME_INDEX_CACHE[0] is static_players:
        return _NAME_INDEX_CACHE[1], _NAME_INDEX_CACHE[2]
    full: _NameIndex = {}
    stripped: _NameIndex = {}
    for p in static_players:
        full.setdefault(normalize_player_name(p["full_name"], False), []).append(p)
        stripped.setdefault(normalize_player_name(p["full_name"]), []).append(p)
    _NAME_INDEX_CACHE = (static_players, full, stripped)
    return full, stripped


def _pick(candidates: list[dict]) -> Optional[int]:
    """Single match wins; among several namesakes prefer the one active player."""
    if len(candidates) == 1:
        return candidates[0]["id"]
    active = [p for p in candidates if p.get("is_active")]
    if len(active) == 1:
        return active[0]["id"]
    return None


def resolve_nba_player_id(
    player_name: str,
    static_players: list[dict] | None = None,
    api_sports_id: int | None = None,
) -> Optional[int]:
    """Match a player name to an NBA.com player_id.

    Order:
      1. MANUAL_PLAYER_IDS (normalized exact match)
      2. nba_api static list — normalized exact match (suffixes kept, then
         stripped, so "Gary Payton II" never folds into his father)
      3. nba_api static list — unambiguous whole-word substring match
         ("Nic Claxton" never matches "Nicolas Claxton"; that needs a pin)
      4. SYNTHETIC_ID_BASE + api_sports_id, when the caller has one
    Ambiguous namesakes resolve to the single active player, else fall through.
    """
    search = normalize_player_name(player_name)
    if not search:
        return None
    if search in MANUAL_PLAYER_IDS:
        return MANUAL_PLAYER_IDS[search]
    if static_players is None:
        static_players = _get_static_players()

    full_index, stripped_index = _name_indexes(static_players)
    exact = full_index.get(normalize_player_name(player_name, False), [])
    if not any(p.get("is_active") for p in exact):
        # Feeds only carry current players: "Gary Payton" from a box score is
        # the active Gary Payton II, not his retired father.
        exact = exact + [p for p in stripped_index.get(search, []) if p not in exact]
    pid = _pick(exact)
    if pid is None and not exact:
        padded = f" {search} "
        partial = [
            p
            for name, players in stripped_index.items()
            if padded in f" {name} " or f" {name} " in padded
            for p in players
        ]
        pid = _pick(partial)
    if pid is not None:
        return pid

    if api_sports_id:
        logger.info(
            "resolve_nba_player_id: no NBA.com id for %r; using synthetic id",
            player_name,
        )
        return SYNTHETIC_ID_BASE + int(api_sports_id)
    return None
