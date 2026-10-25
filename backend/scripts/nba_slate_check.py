"""Read-only check of the stored projections for one NBA slate.

Shows, for a date (default: today, ET), how many games have totals and spread
projections (with their latest write time and pick mix) and, per prop stat, how
many projections exist and how many carry a sportsbook line. Run it after the
midday pregame refresh to confirm it wrote fresh rows and picked up prop lines.

    PYTHONPATH=. python3 scripts/nba_slate_check.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.models.predictions_models import NBASpreadProjections, NBATotalsProjections
from app.services.etl.nba.calculate_prediction_accuracy import STAT_CONFIGS

PROP_STATS = ("points", "rebounds", "assists")


def game_report(db, label, model, extra):
    rows = db.query(model).filter(model.game_date == ARGS_DATE).all()
    print(f"\n== {label}: {len(rows)} games")
    if not rows:
        return
    stamps = [r.created_at for r in rows if r.created_at]
    if stamps:
        print(f"  written {min(stamps):%H:%M} - {max(stamps):%H:%M} UTC")
    print(f"  with market line: {sum(1 for r in rows if extra(r))}")
    print(f"  recommendations: {dict(Counter(r.recommendation for r in rows))}")


def prop_report(db, stat):
    pm = STAT_CONFIGS[stat]["projection_model"]
    rows = db.query(pm).filter(pm.date == ARGS_DATE).all()
    lined = sum(1 for r in rows if getattr(r, "fanduel_line", None))
    pct = f"{lined / len(rows):.0%}" if rows else "n/a"
    print(f"  {stat}: {len(rows)} projections, {lined} with a line ({pct})")


ARGS_DATE = date.today()


def main() -> None:
    global ARGS_DATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="slate date (default: today, ET)")
    args = ap.parse_args()
    ARGS_DATE = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(ZoneInfo("America/New_York")).date()
    )
    print(f"NBA slate check for {ARGS_DATE}")
    db = SessionLocal()
    try:
        game_report(db, "totals", NBATotalsProjections, lambda r: r.market_total)
        game_report(db, "spreads", NBASpreadProjections, lambda r: r.market_spread_home)
        print("\n== props")
        for stat in PROP_STATS:
            prop_report(db, stat)
    finally:
        db.close()


if __name__ == "__main__":
    main()
