"""Store completed-game actuals into pred_wnba_totals_actuals and pred_wnba_spread_actuals.

Reads the ESPN scoreboard for each date in ``grading_dates("wnba")`` (the last few
Eastern days, so a missed night heals on the next run). For each `completed=True` game:
- upsert WNBATotalsActuals (home/away score, sum)
- upsert WNBASpreadActuals (margin, home_won)
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from app.core.database import SessionLocal
from app.models.predictions_models import WNBASpreadActuals, WNBATotalsActuals
from app.services.etl.grading_window import grading_dates
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import fetch_games, now_eastern
from app.services.etl.wnba._team_id_map import normalize_team_name

logger = logging.getLogger(__name__)


def run(target_date: date | None = None) -> dict:
    """Grade ``target_date`` or, by default, the whole lookback window (upserts)."""
    if target_date is not None:
        dates = [target_date]
    else:
        dates = grading_dates("wnba", today=now_eastern().date())

    db = SessionLocal()
    totals_rows: list[dict] = []
    spreads_rows: list[dict] = []
    try:
        for day in dates:
            _collect_day(day, totals_rows, spreads_rows)

        if totals_rows:
            upsert_many(
                db,
                WNBATotalsActuals,
                totals_rows,
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
        if spreads_rows:
            upsert_many(
                db,
                WNBASpreadActuals,
                spreads_rows,
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
        db.commit()
        return {
            "status": "ok",
            "date": dates[-1].isoformat(),
            "dates": [d.isoformat() for d in dates],
            "totals_written": len(totals_rows),
            "spreads_written": len(spreads_rows),
        }
    finally:
        db.close()


def _collect_day(day: date, totals_rows: list[dict], spreads_rows: list[dict]) -> None:
    for g in fetch_games(day):
        if not g.get("completed"):
            continue
        home_score = g.get("home_score")
        away_score = g.get("away_score")
        if home_score is None or away_score is None:
            continue
        home_name = normalize_team_name(g["home_team_name"])
        away_name = normalize_team_name(g["away_team_name"])

        now = datetime.utcnow()
        totals_rows.append(
            {
                "game_date": day,
                "home_team_name": home_name,
                "away_team_name": away_name,
                "home_score": home_score,
                "away_score": away_score,
                "actual_total": home_score + away_score,
                "created_at": now,
            }
        )
        spreads_rows.append(
            {
                "game_date": day,
                "home_team_name": home_name,
                "away_team_name": away_name,
                "home_score": home_score,
                "away_score": away_score,
                "actual_margin": home_score - away_score,
                "home_won": home_score > away_score,
                "created_at": now,
            }
        )


if __name__ == "__main__":
    print(run())
