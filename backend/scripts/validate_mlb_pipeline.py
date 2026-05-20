#!/usr/bin/env python3
"""Post-run row counts for MLB ETL on Railway."""

from __future__ import annotations

import sys

from app.core.database import SessionLocal
from app.models.predictions_models import (
    BlowoutChances,
    GameProjections,
    Homer,
    Pitcher,
    ProjectedHits,
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
        games = db.query(GameProjections).filter(GameProjections.date == today).count()
        hits_today = db.query(ProjectedHits).filter(ProjectedHits.date == today).count()
        blowouts = db.query(BlowoutChances).count()
    finally:
        db.close()

    print(f"date (ET): {today}")
    print(f"  pred_pitcher rows (all): {pitchers}")
    print(f"  pred_homer rows (all): {homers}")
    print(f"  pred_strikeout_projections today: {k_proj}")
    print(f"  pred_game_projections today: {games}")
    print(f"  pred_projected_hits today: {hits_today}")
    print(f"  pred_blowout_chances rows (all): {blowouts}")
    print()

    ok = True
    if pitchers <= 0:
        print("FAIL: pred_pitcher empty — run mlb.strikeouts first")
        ok = False
    if k_proj <= 0:
        print("FAIL: no strikeout projections for today")
        ok = False
    if games <= 0:
        print("WARN: no game projections for today (off-day or pipeline incomplete)")
    if hits_today <= 0:
        print("WARN: no projected hits for today")
    if blowouts <= 0:
        print("WARN: pred_blowout_chances empty — run mlb.blowouts")

    if ok:
        print("PASS: core MLB projection tables populated (pitchers + K projections).")
    else:
        print("FAIL: run run_mlb_update_pipeline on celery-worker first.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
