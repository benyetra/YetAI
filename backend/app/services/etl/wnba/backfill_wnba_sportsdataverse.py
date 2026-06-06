"""Bulk backfill pred_wnba_recent_games from SportsDataverse ESPN parquet (no stats.nba.com per-game calls).

Uses load_wnba_player_boxscore() — same data as wehoop's load_wnba_player_box() — downloaded
from SportsDataverse releases (~seconds per season vs hours of stats.nba.com box scores).

Player IDs come from a season cache built via one LeagueDashPlayerStats call per season
(see cache_wnba_player_ids.py). Advanced stats (usage, ORtg) are not in ESPN box data;
run a separate advanced pass when stats.nba.com is healthy, or train without them.

    cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.cache_wnba_player_ids --seasons 2024,2025
    cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.backfill_wnba_sportsdataverse --seasons 2024,2025
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from typing import Any

import pandas as pd
from sportsdataverse.wnba import load_wnba_player_boxscore

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._player_id_cache import (
    cache_path,
    load_season_cache,
    resolve_player_id,
)
from app.services.etl.wnba._shooting_metrics import enrich_boxscore_row
from app.services.etl.wnba._team_id_map import espn_to_wnba_id

logger = logging.getLogger(__name__)

REGULAR_SEASON_TYPE = 2


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_upsert(
    row: Any,
    *,
    player_id: int,
    opponent_team_id: int,
    home_game: bool | None,
) -> dict[str, Any]:
    game_date = row["game_date"]
    if hasattr(game_date, "date"):
        game_date = game_date.date()
    base = {
        "player_id": player_id,
        "game_date": game_date,
        "opponent_team_id": opponent_team_id,
        "points": _optional_float(row.get("points")),
        "fg_attempts": _optional_float(row.get("field_goals_attempted")),
        "fg_percentage": None,
        "three_pt_attempts": _optional_float(
            row.get("three_point_field_goals_attempted")
        ),
        "three_pt_percentage": None,
        "three_pt_made": _optional_float(row.get("three_point_field_goals_made")),
        "ft_attempts": _optional_float(row.get("free_throws_attempted")),
        "ft_percentage": None,
        "minutes": _optional_float(row.get("minutes")),
        "field_goals_made": _optional_float(row.get("field_goals_made")),
        "free_throws_made": _optional_float(row.get("free_throws_made")),
        "offensive_rebounds": _optional_float(row.get("offensive_rebounds")),
        "defensive_rebounds": _optional_float(row.get("defensive_rebounds")),
        "rebounds": _optional_float(row.get("rebounds")),
        "assists": _optional_float(row.get("assists")),
        "turnovers": _optional_float(row.get("turnovers")),
        "steals": _optional_float(row.get("steals")),
        "blocks": _optional_float(row.get("blocks")),
        "personal_fouls": _optional_float(row.get("fouls")),
        "home_game": home_game,
        "plus_minus": _optional_float(row.get("plus_minus")),
    }
    return enrich_boxscore_row(base)


def run(
    seasons: list[int] | None = None,
    *,
    require_cache: bool = True,
) -> dict:
    seasons = seasons or [2021, 2022, 2023, 2024, 2025]
    missing_cache = [s for s in seasons if not cache_path(s).exists()]
    if require_cache and missing_cache:
        return {
            "status": "error",
            "reason": "missing_player_id_cache",
            "missing_seasons": missing_cache,
            "hint": (
                "Run cache_wnba_player_ids when stats.nba.com responds "
                "(one league call per season, not per game)."
            ),
        }

    caches: dict[int, dict[str, int]] = {s: load_season_cache(s) for s in seasons}
    db = SessionLocal()
    pending: list[dict] = []
    rows_written = 0
    rows_skipped_no_id = 0
    rows_skipped_team = 0

    try:
        for season in seasons:
            logger.info("sdv backfill: loading season %s player box parquet", season)
            frame = load_wnba_player_boxscore(seasons=[season], return_as_pandas=True)
            regular = frame[frame["season_type"] == REGULAR_SEASON_TYPE]
            logger.info(
                "sdv backfill: season %s → %d regular-season rows", season, len(regular)
            )

            for _, row in regular.iterrows():
                team_id = espn_to_wnba_id(str(int(row["team_id"])))
                opp_id = espn_to_wnba_id(str(int(row["opponent_team_id"])))
                if team_id is None or opp_id is None:
                    rows_skipped_team += 1
                    continue

                player_id = resolve_player_id(
                    season=season,
                    team_id=team_id,
                    athlete_display_name=str(row["athlete_display_name"]),
                    caches=caches,
                )
                if player_id is None:
                    rows_skipped_no_id += 1
                    continue

                home_raw = str(row.get("home_away") or "").lower()
                home_game = (
                    True
                    if home_raw == "home"
                    else False if home_raw == "away" else None
                )

                pending.append(
                    _row_to_upsert(
                        row,
                        player_id=player_id,
                        opponent_team_id=opp_id,
                        home_game=home_game,
                    )
                )

                if len(pending) >= 500:
                    upsert_many(
                        db,
                        WNBARecentGames,
                        pending,
                        conflict_keys=["player_id", "game_date"],
                    )
                    rows_written += len(pending)
                    pending.clear()
                    db.commit()

        if pending:
            upsert_many(
                db,
                WNBARecentGames,
                pending,
                conflict_keys=["player_id", "game_date"],
            )
            rows_written += len(pending)
            db.commit()

        return {
            "status": "ok",
            "seasons": seasons,
            "rows_written": rows_written,
            "rows_skipped_no_player_id": rows_skipped_no_id,
            "rows_skipped_team_map": rows_skipped_team,
        }
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill WNBA recent games from SportsDataverse ESPN parquet"
    )
    parser.add_argument(
        "--seasons",
        default="2021,2022,2023,2024,2025",
        help="Comma-separated season years",
    )
    parser.add_argument(
        "--allow-missing-cache",
        action="store_true",
        help="Proceed even if player-id cache files are missing (most rows will skip)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    print(
        json.dumps(
            run(seasons=seasons, require_cache=not args.allow_missing_cache),
            indent=2,
            default=str,
        )
    )
