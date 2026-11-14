#!/usr/bin/env python3
"""Regrade NBA prop actuals, accuracy rows and totals actuals from the box scores (NBA-10).

pred_*_actuals must match pred_recent_games exactly: a row exists only when the
player has a box value on that date against the projected opponent. This walks a
date range, deleting stale/mismatched actuals, correcting values, inserting
missing rows, refreshing pred_prediction_accuracy and filling pred_nba_totals_actuals
for games whose finals were stored after the grading window passed. Idempotent.

Dry run is the default (per-stat updated / deleted / inserted / unchanged counts):
  cd backend
  PYTHONPATH=. python3 scripts/nba_regrade_actuals.py --start 2026-10-20 --end 2026-11-13
Write the corrections, then re-count (must be all zero):
  PYTHONPATH=. python3 scripts/nba_regrade_actuals.py --start 2026-10-20 --end 2026-11-13 --apply
Defaults: --start this season's opener, --end yesterday (Eastern).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from typing import Any

CHANGE_KEYS = ("updated", "deleted", "inserted")


def _dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _totals_to_fill(game_date: date) -> int:
    """Projected games with an ESPN final but no pred_nba_totals_actuals row."""
    from app.models.predictions_models import NBATotalsActuals, NBATotalsProjections
    from app.services.etl.nba import totals_accuracy_tracker as tat

    projections = (
        tat.db.query(NBATotalsProjections).filter_by(game_date=game_date).all()
    )
    finals = tat.final_scores_from_actuals(game_date)
    n = 0
    for proj in projections:
        if not tat.match_projection_to_actual(proj, finals):
            continue
        have = (
            tat.db.query(NBATotalsActuals)
            .filter_by(
                game_date=game_date,
                home_team_name=proj.home_team_name,
                away_team_name=proj.away_team_name,
            )
            .first()
        )
        n += have is None
    return n


def count_changes(db, start: date, end: date) -> dict[str, Any]:
    """Read-only: what regrading start..end would change."""
    from app.services.etl.nba import calculate_prediction_accuracy as cpa
    from app.services.etl.nba import store_actuals as sa
    from app.services.etl.nba import totals_accuracy_tracker as tat

    cpa.db = tat.db = db
    stats = {
        k: dict.fromkeys(("updated", "deleted", "inserted", "unchanged"), 0)
        for k in sa.GRADED_STATS
    }
    accuracy = dict.fromkeys(("created", "updated", "deleted", "unchanged"), 0)
    totals = 0
    for d in _dates(start, end):
        for key in sa.GRADED_STATS:
            for k, v in sa.plan_counts(db, key, d).items():
                stats[key][k] += v
        for k, v in cpa.calculate_accuracy_for_date(d, dry_run=True).items():
            accuracy[k] += v
        totals += _totals_to_fill(d)
    return {"stats": stats, "accuracy": accuracy, "totals_to_fill": totals}


def total_changes(counts: dict[str, Any]) -> int:
    acc = counts["accuracy"]
    return (
        sum(s[k] for s in counts["stats"].values() for k in CHANGE_KEYS)
        + acc["created"]
        + acc["updated"]
        + acc["deleted"]
        + counts["totals_to_fill"]
    )


def apply_range(db, start: date, end: date) -> None:
    """Store actuals, accuracy and totals for every date in the range."""
    from app.services.etl.nba import calculate_prediction_accuracy as cpa
    from app.services.etl.nba import store_actuals as sa
    from app.services.etl.nba import totals_accuracy_tracker as tat

    cpa.db = tat.db = db
    for d in _dates(start, end):
        sa.store_date(db, d)
        cpa.calculate_accuracy_for_date(d)
        tat._update_results_for(d)


def _print(label: str, counts: dict[str, Any]) -> None:
    print(f"== {label}")
    for key, c in counts["stats"].items():
        print(f"  {key:12s} {c}")
    print(f"  accuracy     {counts['accuracy']}")
    print(f"  totals games to fill: {counts['totals_to_fill']}")
    print(f"  total changes: {total_changes(counts)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, help="first date (ISO)")
    parser.add_argument("--end", type=date.fromisoformat, help="last date (ISO)")
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default: dry run)"
    )
    parser.add_argument("--dry-run", action="store_true", help="explicit dry run")
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    from scripts._db_script_guard import assert_not_local_default_db

    assert_not_local_default_db()

    from app.core.database import SessionLocal
    from app.services.etl.grading_window import eastern_today
    from app.services.etl.nba._season import season_opener

    end = args.end or eastern_today() - timedelta(days=1)
    start = args.start or season_opener(end)

    db = SessionLocal()
    try:
        _print(
            f"{'BEFORE' if apply else 'DRY RUN'} {start}..{end}",
            count_changes(db, start, end),
        )
        if apply:
            apply_range(db, start, end)
            after = count_changes(db, start, end)
            _print("AFTER (must be zero changes)", after)
            return 0 if total_changes(after) == 0 else 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
