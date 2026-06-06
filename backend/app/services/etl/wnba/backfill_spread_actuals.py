"""One-shot backfill of pred_wnba_spread_actuals from nba_api LeagueGameFinder.

Uses the same WNBA league game list as backfill_wnba_history but writes one row
per completed game (home/away scores and margin). Idempotent via upsert.

    cd backend && python -m app.services.etl.wnba.backfill_spread_actuals
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import WNBASpreadActuals, WNBATotalsActuals
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import fetch_games
from app.services.etl.wnba._team_id_map import WNBA_ID_TO_NAME, normalize_team_name
from app.services.etl.wnba._wnba_stats import fetch_games_for_season
from app.services.etl.wnba.backfill_wnba_history import DEFAULT_SEASONS

logger = logging.getLogger(__name__)

_VALID_SEASONS = frozenset({"2021", "2022", "2023", "2024", "2025", "2026"})


def _seasons_for_window(
    season_start: date | None,
    season_end: date | None,
    seasons: list[str] | None,
) -> list[str]:
    if seasons:
        return seasons
    if season_start is None and season_end is None:
        return DEFAULT_SEASONS
    lo_year = (season_start or date(2021, 1, 1)).year
    hi_year = (season_end or date.today()).year
    return [str(y) for y in range(lo_year, hi_year + 1) if str(y) in _VALID_SEASONS]


def _home_team_id(teams: list[dict]) -> int | None:
    for t in teams:
        matchup = t.get("MATCHUP") or ""
        if "vs." in matchup:
            return int(t["TEAM_ID"])
    return None


def run_from_totals(
    *,
    season_start: date | None = None,
    season_end: date | None = None,
) -> dict:
    """Copy completed scores from pred_wnba_totals_actuals (no external API)."""
    db = SessionLocal()
    rows: list[dict] = []
    try:
        q = db.query(WNBATotalsActuals)
        if season_start:
            q = q.filter(WNBATotalsActuals.game_date >= season_start)
        if season_end:
            q = q.filter(WNBATotalsActuals.game_date <= season_end)
        for actual in q.all():
            rows.append(
                {
                    "game_date": actual.game_date,
                    "home_team_name": actual.home_team_name,
                    "away_team_name": actual.away_team_name,
                    "home_score": actual.home_score,
                    "away_score": actual.away_score,
                    "actual_margin": actual.home_score - actual.away_score,
                    "home_won": actual.home_score > actual.away_score,
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
        return {"status": "ok", "source": "totals", "rows_written": len(rows)}
    finally:
        db.close()


def run_espn(
    *,
    season_start: date,
    season_end: date,
    sleep_seconds: float = 0.15,
) -> dict:
    """Backfill from ESPN scoreboard per day (works from CI; slower than nba_api)."""
    db = SessionLocal()
    rows: list[dict] = []
    games_seen = 0
    games_skipped = 0
    try:
        day = season_start
        while day <= season_end:
            for g in fetch_games(day):
                if not g.get("completed"):
                    games_skipped += 1
                    continue
                home_score = g.get("home_score")
                away_score = g.get("away_score")
                if home_score is None or away_score is None:
                    games_skipped += 1
                    continue
                home_name = normalize_team_name(g["home_team_name"])
                away_name = normalize_team_name(g["away_team_name"])
                games_seen += 1
                rows.append(
                    {
                        "game_date": day,
                        "home_team_name": home_name,
                        "away_team_name": away_name,
                        "home_score": int(home_score),
                        "away_score": int(away_score),
                        "actual_margin": int(home_score) - int(away_score),
                        "home_won": int(home_score) > int(away_score),
                        "created_at": datetime.utcnow(),
                    }
                )
            day += timedelta(days=1)
            if sleep_seconds:
                time.sleep(sleep_seconds)

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
            "source": "espn",
            "games_seen": games_seen,
            "games_skipped": games_skipped,
            "rows_written": len(rows),
        }
    finally:
        db.close()


def run_nba_api(
    seasons: list[str] | None = None,
    *,
    season_start: date | None = None,
    season_end: date | None = None,
) -> dict:
    seasons = _seasons_for_window(season_start, season_end, seasons)
    db = SessionLocal()
    rows: list[dict] = []
    games_seen = 0
    games_skipped = 0

    try:
        for season in seasons:
            logger.info("backfill_spread_actuals: season %s", season)
            games = fetch_games_for_season(season, profile="backfill")
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
            "source": "nba_api",
            "seasons": seasons,
            "games_seen": games_seen,
            "games_skipped": games_skipped,
            "rows_written": len(rows),
        }
    finally:
        db.close()


def run(
    *,
    source: str = "nba_api",
    season_start: date | None = None,
    season_end: date | None = None,
    seasons: list[str] | None = None,
) -> dict:
    if source == "totals":
        return run_from_totals(season_start=season_start, season_end=season_end)
    if source == "espn":
        if not season_start or not season_end:
            raise ValueError("espn source requires --start and --end")
        return run_espn(season_start=season_start, season_end=season_end)
    if source == "nba_api":
        return run_nba_api(seasons, season_start=season_start, season_end=season_end)
    raise ValueError(f"unknown source: {source}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill WNBA spread actuals")
    parser.add_argument(
        "--source",
        choices=("totals", "espn", "nba_api"),
        default="nba_api",
    )
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
    print(run(source=args.source, season_start=start, season_end=end))
