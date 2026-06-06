"""Season-scoped ESPN name → stats.wnba.com player_id cache."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.services.etl.wnba import _wnba_stats

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "wnba_player_id_cache"


def normalize_player_name(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(name).lower()).strip()


def cache_path(season: str | int) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{season}.json"


def load_season_cache(season: str | int) -> dict[str, int]:
    """Return map of 'team_id|normalized_name' → player_id."""
    path = cache_path(season)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {str(k): int(v) for k, v in raw.items()}


def save_season_cache(season: str | int, mapping: dict[str, int]) -> Path:
    path = cache_path(season)
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True))
    return path


def cache_key(team_id: int, player_name: str) -> str:
    return f"{team_id}|{normalize_player_name(player_name)}"


def build_season_cache(
    season: str | int, *, profile: str = "backfill"
) -> dict[str, int]:
    """One league-wide stats.wnba.com call → name map for the season."""
    rows = _wnba_stats.fetch_league_player_stats(season=str(season), profile=profile)
    mapping: dict[str, int] = {}
    for row in rows:
        team_id = row.get("TEAM_ID")
        player_id = row.get("PLAYER_ID")
        player_name = row.get("PLAYER_NAME")
        if team_id is None or player_id is None or not player_name:
            continue
        key = cache_key(int(team_id), str(player_name))
        mapping[key] = int(player_id)
    return mapping


def resolve_player_id(
    *,
    season: int,
    team_id: int,
    athlete_display_name: str,
    caches: dict[int, dict[str, int]],
) -> int | None:
    season_map = caches.get(season) or load_season_cache(season)
    if season not in caches:
        caches[season] = season_map
    return season_map.get(cache_key(team_id, athlete_display_name))
