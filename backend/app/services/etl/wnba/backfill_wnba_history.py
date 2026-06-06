"""One-shot historical backfill for pred_wnba_recent_games.

Pulls 2021-2025 regular-season box scores via nba_api (LeagueID=10) and
upserts one row per player-game into pred_wnba_recent_games.

Not registered as a Celery task — run manually:

    cd backend && ./.venv/bin/python -m app.services.etl.wnba.backfill_wnba_history

or via an admin endpoint. Re-runs are idempotent (upsert on
(player_id, game_date)).
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._boxscore_fetch import (
    advanced_by_player_id,
    fetch_advanced_boxscore,
    fetch_traditional_boxscore,
    player_game_row_from_boxscore,
)
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._wnba_stats import (
    StatsNbaUnavailable,
    fetch_games_for_season,
)

logger = logging.getLogger(__name__)

DEFAULT_SEASONS: list[str] = ["2021", "2022", "2023", "2024", "2025"]
DEFAULT_REQUEST_DELAY_SECONDS = 0.75


def _fetch_boxscore(game_id: str, *, profile: str = "backfill") -> list[dict[str, Any]]:
    """Return one row per player for one game (traditional box score)."""
    return fetch_traditional_boxscore(game_id, profile=profile)


def run(
    seasons: list[str] | None = None,
    *,
    skip_advanced: bool = False,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    fetch_profile: str = "backfill",
) -> dict:
    seasons = seasons or DEFAULT_SEASONS
    db = SessionLocal()
    total_rows_written = 0
    total_games_processed = 0
    total_games_skipped = 0
    total_advanced_skipped = 0
    pending_rows: list[dict] = []

    def _flush_pending() -> None:
        nonlocal total_rows_written
        if not pending_rows:
            return
        upsert_many(
            db,
            WNBARecentGames,
            pending_rows,
            conflict_keys=["player_id", "game_date"],
        )
        total_rows_written += len(pending_rows)
        pending_rows.clear()

    try:
        for season in seasons:
            logger.info("backfill: fetching games for season %s", season)
            try:
                games = fetch_games_for_season(season, profile=fetch_profile)
            except StatsNbaUnavailable as exc:
                logger.error(
                    "season game list failed for %s after retries: %s", season, exc
                )
                raise
            # Group by GAME_ID so we can identify both teams per game.
            by_game: dict[str, list[dict[str, Any]]] = {}
            for g in games:
                by_game.setdefault(g["GAME_ID"], []).append(g)

            for game_id, teams in by_game.items():
                if not teams:
                    total_games_skipped += 1
                    continue
                team_a = teams[0]
                game_date_str = team_a.get("GAME_DATE")
                if not game_date_str:
                    total_games_skipped += 1
                    continue
                try:
                    game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
                except ValueError:
                    total_games_skipped += 1
                    continue

                # Determine home team from MATCHUP string. "X vs. Y" → X home; "X @ Y" → X away.
                home_team_id = None
                for t in teams:
                    if "vs." in (t.get("MATCHUP") or ""):
                        home_team_id = int(t["TEAM_ID"])
                        break

                try:
                    boxscore_rows = _fetch_boxscore(game_id, profile=fetch_profile)
                except StatsNbaUnavailable as exc:
                    logger.warning(
                        "boxscore fetch failed for %s after retries: %s", game_id, exc
                    )
                    total_games_skipped += 1
                    continue

                if not boxscore_rows:
                    total_games_skipped += 1
                    continue

                adv_rows: list[dict[str, Any]] = []
                if not skip_advanced:
                    try:
                        adv_rows = fetch_advanced_boxscore(
                            game_id, profile=fetch_profile
                        )
                    except StatsNbaUnavailable as exc:
                        logger.warning(
                            "advanced boxscore fetch failed for %s: %s", game_id, exc
                        )
                        total_advanced_skipped += 1
                adv_map = advanced_by_player_id(adv_rows)

                # Build team_id → opponent map. Prefer the games list (2 rows per game);
                # fall back to deriving the two distinct TEAM_IDs from the boxscore rows.
                if len(teams) == 2:
                    team_b = teams[1]
                    team_id_to_opp = {
                        int(team_a["TEAM_ID"]): int(team_b["TEAM_ID"]),
                        int(team_b["TEAM_ID"]): int(team_a["TEAM_ID"]),
                    }
                else:
                    distinct_team_ids = list(
                        {
                            int(r["TEAM_ID"])
                            for r in boxscore_rows
                            if r.get("TEAM_ID") is not None
                        }
                    )
                    if len(distinct_team_ids) != 2:
                        total_games_skipped += 1
                        continue
                    t1, t2 = distinct_team_ids
                    team_id_to_opp = {t1: t2, t2: t1}

                for row in boxscore_rows:
                    player_id = row.get("PLAYER_ID")
                    if player_id is None:
                        continue
                    team_id = int(row["TEAM_ID"])
                    opp_id = team_id_to_opp.get(team_id)
                    if opp_id is None:
                        continue

                    pending_rows.append(
                        player_game_row_from_boxscore(
                            row,
                            game_date=game_date,
                            opponent_team_id=opp_id,
                            home_game=(
                                (home_team_id == team_id) if home_team_id else None
                            ),
                            adv_row=adv_map.get(int(player_id)),
                        )
                    )

                total_games_processed += 1
                if request_delay_seconds > 0:
                    time.sleep(request_delay_seconds)
                if total_games_processed % 50 == 0:
                    _flush_pending()
                    db.commit()
                    logger.info(
                        "backfill: %d games, %d rows written (season %s)",
                        total_games_processed,
                        total_rows_written,
                        season,
                    )

        _flush_pending()
        db.commit()
        return {
            "status": "ok",
            "seasons": seasons,
            "games_processed": total_games_processed,
            "games_skipped": total_games_skipped,
            "advanced_fetch_skipped": total_advanced_skipped,
            "rows_written": total_rows_written,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser(description="Backfill WNBA player-game history")
    parser.add_argument(
        "--seasons",
        default=",".join(DEFAULT_SEASONS),
        help="Comma-separated season years (default: 2021-2025)",
    )
    parser.add_argument(
        "--skip-advanced",
        action="store_true",
        help="Skip BoxScoreAdvancedV2 (traditional box only)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help="Seconds to sleep between games (rate limit; default 0.75)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    seasons = [s.strip() for s in args.seasons.split(",") if s.strip()]
    print(
        json.dumps(
            run(
                seasons=seasons,
                skip_advanced=args.skip_advanced,
                request_delay_seconds=args.delay,
            ),
            indent=2,
            default=str,
        )
    )
