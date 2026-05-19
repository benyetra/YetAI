#!/usr/bin/env python3
"""Post-run row counts for MLB ETL on Railway."""

from __future__ import annotations

import sys

from app.core.database import SessionLocal
from app.models.predictions_models import (
    GameProjections,
    Homer,
    Pitcher,
    StrikeoutProjections,
)
from app.services.etl.nba._espn import now_eastern


def main() -> int:
    today = now_eastern().date()
    db = SessionLocal()
    try:
        pitchers = db.query(Pitcher).count()
        homers = db.query(Homer).count()
        k_proj = (
            db.query(StrikeoutProjections)
            .filter(StrikeoutProjections.date == today)
            .count()
        )
        games = (
            db.query(GameProjections)
            .filter(GameProjections.date == today)
            .count()
        )
    finally:
        db.close()

    print(f"date (ET): {today}")
    print(f"  pred_pitcher rows: {pitchers}")
    print(f"  pred_homer rows: {homers}")
    print(f"  pred_strikeout_projections today: {k_proj}")
    print(f"  pred_game_projections today: {games}")

    ok = pitchers > 0 and k_proj > 0
    if ok:
        print("PASS: MLB projection tables populated.")
    else:
        print("FAIL: run run_mlb_update_pipeline on celery-worker first.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
