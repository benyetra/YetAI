#!/usr/bin/env python3
"""Post-run checks for NBA ETL on Railway (projections + accuracy grading).

Usage (from backend/ on worker or locally with DATABASE_URL):

    PYTHONPATH=. python scripts/validate_nba_pipeline.py
"""

from __future__ import annotations

import sys
from datetime import timedelta

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.predictions_models import (
    PointsProjections,
    PredictionAccuracy,
    PRAProjections,
    RecentGames,
)
from app.services.etl.nba._espn import now_eastern


def main() -> int:
    today = now_eastern().date()
    yesterday = today - timedelta(days=1)
    db = SessionLocal()
    try:
        points = db.query(PointsProjections).filter(PointsProjections.date == today).count()
        pra = db.query(PRAProjections).filter(PRAProjections.date == today).count()
        acc_y = (
            db.query(PredictionAccuracy)
            .filter(PredictionAccuracy.game_date == yesterday)
            .count()
        )
        proj_y = (
            db.query(PointsProjections)
            .filter(PointsProjections.date == yesterday)
            .count()
        )
        rg_y = (
            db.query(RecentGames).filter(RecentGames.game_date == yesterday).count()
        )
        by_stat = (
            db.query(PredictionAccuracy.stat_type, func.count())
            .filter(PredictionAccuracy.game_date == yesterday)
            .group_by(PredictionAccuracy.stat_type)
            .all()
        )
    finally:
        db.close()

    print(f"ET date (US/Eastern): today={today} yesterday={yesterday}")
    print()
    print("--- Today's projections ---")
    print(f"  points: {points}  (expect >= 20 on a normal slate)")
    print(f"  pra:    {pra}     (expect >= 10; often fewer than points)")
    print()
    print("--- Yesterday accuracy (grading targets prior day) ---")
    print(f"  projections (points, {yesterday}): {proj_y}")
    print(f"  recent_games actuals ({yesterday}): {rg_y}")
    print(f"  pred_prediction_accuracy rows: {acc_y}")
    if by_stat:
        for stat, n in sorted(by_stat):
            print(f"    {stat}: {n}")
    if acc_y == 0 and proj_y == 0 and rg_y > 0:
        print(
            "  NOTE: actuals exist but no projections for yesterday — "
            "accuracy stays 0 until you've run the pipeline on that date."
        )
    elif acc_y == 0 and proj_y > 0 and rg_y == 0:
        print("  NOTE: projections exist; waiting on game actuals in recent_games.")
    print()

    ok = True
    if points < 20:
        print("FAIL: points projections below threshold")
        ok = False
    if pra < 10:
        print("FAIL: PRA projections below threshold")
        ok = False
    # accuracy > 0 is a tomorrow-morning check after first full day of stored projections
    if ok:
        print("PASS: today's projection counts look healthy.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
