"""Store completed NBA game scores into pred_nba_spread_actuals.

Final scores come from ESPN's scoreboard with team names in the Odds API
spelling pred_nba_game_lines uses, so spread projections, Elo and the training
join line up. Every completed game is stored — Elo needs all of them, not only
the games we had a line for.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import NBASpreadActuals
from app.services.etl.nba._espn import fetch_final_scores, now_eastern
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)


def actual_rows(game_date: date, finals: list[dict]) -> list[dict]:
    """pred_nba_spread_actuals rows from fetch_final_scores output."""
    rows = []
    for g in finals:
        margin = g["home_score"] - g["away_score"]
        rows.append(
            {
                "game_date": game_date,
                "home_team_name": g["home_team_name"],
                "away_team_name": g["away_team_name"],
                "home_score": g["home_score"],
                "away_score": g["away_score"],
                "actual_margin": margin,
                "home_won": margin > 0,
                "created_at": datetime.utcnow(),
            }
        )
    return rows


def run(target_date=None) -> dict:
    if target_date is None:
        target_date = now_eastern().date() - timedelta(days=1)

    rows = actual_rows(target_date, fetch_final_scores(target_date))
    db = SessionLocal()
    try:
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
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
