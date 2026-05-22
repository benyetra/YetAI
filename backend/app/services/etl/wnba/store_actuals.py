"""Store completed-game actuals into pred_wnba_totals_actuals and pred_wnba_spread_actuals.

Reads from ESPN scoreboard for yesterday (Eastern). For each `completed=True` game:
- upsert WNBATotalsActuals (home/away score, sum)
- upsert WNBASpreadActuals (margin, home_won)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import WNBASpreadActuals, WNBATotalsActuals
from app.services.etl.wnba._espn import fetch_games, now_eastern
from app.services.etl.wnba._team_id_map import normalize_team_name

logger = logging.getLogger(__name__)


def run(target_date: date | None = None) -> dict:
    if target_date is None:
        target_date = now_eastern().date() - timedelta(days=1)

    games = fetch_games(target_date)
    db = SessionLocal()
    totals_written = 0
    spreads_written = 0
    try:
        for g in games:
            if not g.get("completed"):
                continue
            home_score = g.get("home_score")
            away_score = g.get("away_score")
            if home_score is None or away_score is None:
                continue
            home_name = normalize_team_name(g["home_team_name"])
            away_name = normalize_team_name(g["away_team_name"])

            db.merge(
                WNBATotalsActuals(
                    game_date=target_date,
                    home_team_name=home_name,
                    away_team_name=away_name,
                    home_score=home_score,
                    away_score=away_score,
                    actual_total=home_score + away_score,
                    created_at=datetime.utcnow(),
                )
            )
            totals_written += 1

            db.merge(
                WNBASpreadActuals(
                    game_date=target_date,
                    home_team_name=home_name,
                    away_team_name=away_name,
                    home_score=home_score,
                    away_score=away_score,
                    actual_margin=home_score - away_score,
                    home_won=home_score > away_score,
                    created_at=datetime.utcnow(),
                )
            )
            spreads_written += 1

        db.commit()
        return {
            "status": "ok",
            "date": target_date.isoformat(),
            "totals_written": totals_written,
            "spreads_written": spreads_written,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
