"""Build season player-id caches (one stats.wnba.com league call per season).

Run when stats.nba.com is responding — NOT during per-game backfill throttling.

    cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.cache_wnba_player_ids --seasons 2024,2025
"""

from __future__ import annotations

import argparse
import json
import logging

from app.services.etl.wnba._player_id_cache import build_season_cache, save_season_cache
from app.services.etl.wnba._wnba_stats import StatsNbaUnavailable

logger = logging.getLogger(__name__)


def run(seasons: list[int], *, profile: str = "backfill") -> dict:
    results: dict[str, object] = {"status": "ok", "seasons": {}}
    for season in seasons:
        logger.info("building player id cache for season %s", season)
        try:
            mapping = build_season_cache(season, profile=profile)
        except StatsNbaUnavailable as exc:
            results["status"] = "partial"
            results["seasons"][str(season)] = {"status": "failed", "error": str(exc)}
            continue
        path = save_season_cache(season, mapping)
        results["seasons"][str(season)] = {
            "status": "ok",
            "players": len(mapping),
            "path": str(path),
        }
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache WNBA player IDs per season")
    parser.add_argument(
        "--seasons",
        default="2021,2022,2023,2024,2025",
        help="Comma-separated season years",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    print(json.dumps(run(seasons), indent=2))
