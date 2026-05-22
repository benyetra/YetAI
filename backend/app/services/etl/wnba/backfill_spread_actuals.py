"""One-shot backfill of pred_wnba_spread_actuals from nba_api LeagueGameFinder.

Uses the same WNBA league game list as backfill_wnba_history but writes one row
per completed game (home/away scores and margin). Idempotent via upsert.

    cd backend && python -m app.services.etl.wnba.backfill_spread_actuals
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from app.core.database import SessionLocal
from app.models.predictions_models import WNBASpreadActuals
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._team_id_map import WNBA_ID_TO_NAME
from app.services.etl.wnba.backfill_wnba_history import (
    DEFAULT_SEASONS,
    _fetch_games_for_season,
)

logger = logging.getLogger(__name__)


def _home_team_id(teams: list[dict]) -> int | None:
    for t in teams:
        matchup = t.get("MATCHUP") or ""
        if "vs." in matchup:
            return int(t["TEAM_ID"])
    return None


def run(
    seasons: list[str] | None = None,
    *,
    season_start: date | None = None,
    season_end: date | None = None,
) -> dict:
    seasons = seasons or DEFAULT_SEASONS
    db = SessionLocal()
    rows: list[dict] = []
    games_seen = 0
    games_skipped = 0

    try:
        for season in seasons:
            logger.info("backfill_spread_actuals: season %s", season)
            games = _fetch_games_for_season(season)
            by_game: dict[str, list[dict]] = {}
            for g in games:
                by_game.setdefault(g["GAME_ID"], []).append(g)

            for game_id, teams in by_game.items():
                if len(teams) != 2:
                    games_skipped += 1
                    continue

                game_date_str = teams[0].get("GAME_DATE")
                if not game_date_str:
                    games_skipped += 1
                    continue
                try:
                    game_date = date.fromisoformat(game_date_str)
                except ValueError:
                    games_skipped += 1
                    continue

                if season_start and game_date < season_start:
                    continue
                if season_end and game_date > season_end:
                    continue

                home_id = _home_team_id(teams)
                if home_id is None:
                    games_skipped += 1
                    continue

                home_row = next(
                    (t for t in teams if int(t["TEAM_ID"]) == home_id), None
                )
                away_row = next(
                    (t for t in teams if int(t["TEAM_ID"]) != home_id), None
                )
                if not home_row or not away_row:
                    games_skipped += 1
                    continue

                home_name = WNBA_ID_TO_NAME.get(int(home_row["TEAM_ID"]))
                away_name = WNBA_ID_TO_NAME.get(int(away_row["TEAM_ID"]))
                if not home_name or not away_name:
                    games_skipped += 1
                    continue

                try:
                    home_score = int(home_row["PTS"])
                    away_score = int(away_row["PTS"])
                except (TypeError, ValueError):
                    games_skipped += 1
                    continue

                games_seen += 1
                rows.append(
                    {
                        "game_date": game_date,
                        "home_team_name": home_name,
                        "away_team_name": away_name,
                        "home_score": home_score,
                        "away_score": away_score,
                        "actual_margin": home_score - away_score,
                        "home_won": home_score > away_score,
                        "created_at": datetime.utcnow(),
                    }
                )

        if rows:
            upsert_many(
                db,
                WNBASpreadActuals,
                rows,
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
        db.commit()
        return {
            "status": "ok",
            "seasons": seasons,
            "games_seen": games_seen,
            "games_skipped": games_skipped,
            "rows_written": len(rows),
        }
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill WNBA spread actuals")
    parser.add_argument(
        "--start",
        help="Optional YYYY-MM-DD lower bound on game_date",
    )
    parser.add_argument(
        "--end",
        help="Optional YYYY-MM-DD upper bound on game_date",
    )
    args = parser.parse_args()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    print(run(season_start=start, season_end=end))
