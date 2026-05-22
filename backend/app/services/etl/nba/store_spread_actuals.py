"""Store completed NBA game scores into pred_nba_spread_actuals.

Team names are taken from pred_nba_game_lines so spread projections join cleanly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import NBAGameLines, NBASpreadActuals
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba.totals_accuracy_tracker import (
    fetch_game_scores_from_api,
    normalize_team_name,
)
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)


def _match_api_score(
    home_name: str, away_name: str, api_games: list[dict]
) -> dict | None:
    proj_home = normalize_team_name(home_name)
    proj_away = normalize_team_name(away_name)
    for g in api_games:
        api_home = normalize_team_name(g["home_team"])
        api_away = normalize_team_name(g["away_team"])
        if (proj_home in api_home or api_home in proj_home) and (
            proj_away in api_away or api_away in proj_away
        ):
            return g
    return None


def run(target_date=None) -> dict:
    if target_date is None:
        target_date = now_eastern().date() - timedelta(days=1)

    api_games = fetch_game_scores_from_api(target_date)
    db = SessionLocal()
    rows: list[dict] = []
    try:
        lines = (
            db.query(NBAGameLines).filter(NBAGameLines.game_date == target_date).all()
        )
        for line in lines:
            matched = _match_api_score(
                line.home_team_name, line.away_team_name, api_games
            )
            if not matched:
                continue
            home_score = int(matched["home_score"])
            away_score = int(matched["away_score"])
            rows.append(
                {
                    "game_date": target_date,
                    "home_team_name": line.home_team_name,
                    "away_team_name": line.away_team_name,
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
                NBASpreadActuals,
                rows,
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
        db.commit()
        return {
            "status": "ok",
            "date": target_date.isoformat(),
            "spreads_written": len(rows),
            "lines_checked": len(lines),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
