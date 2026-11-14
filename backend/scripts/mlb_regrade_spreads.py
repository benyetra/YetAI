#!/usr/bin/env python3
"""Recompute pred_game_actuals.spread_correct with the fixed grade_spread (MLB-3).

grade_spread used to compare the margin to the home line without adding it, so a
home -1.5 favourite winning by 1 graded as covered. This recomputes spread_correct
from the stored final scores and the projection's stored market_spread /
spread_recommendation. Idempotent: rows already correct are left alone.

Dry run is the default (prints changed / unchanged / flipped counts):
  cd backend
  PYTHONPATH=. python3 scripts/mlb_regrade_spreads.py --start 2025-03-01 --end 2025-11-30
Write the corrections:
  PYTHONPATH=. python3 scripts/mlb_regrade_spreads.py --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Any, Iterable

from app.services.mlb_game_picks import derive_spread_recommendation_row, grade_spread


def regraded_spread(actual: Any, proj: Any) -> bool | None:
    """spread_correct for one game from stored scores + projection (None = no call/push)."""
    if actual.home_score is None or actual.away_score is None:
        return actual.spread_correct  # no final score: leave as stored
    if proj.market_spread is None:
        return None
    pick = proj.spread_recommendation or derive_spread_recommendation_row(
        {"run_line": proj.run_line, "market_spread": proj.market_spread}
    )
    if not pick:
        return None
    return grade_spread(
        pick,
        home_score=int(actual.home_score),
        away_score=int(actual.away_score),
        market_spread_home=float(proj.market_spread),
    )


def regrade_spreads(pairs: Iterable[tuple[Any, Any]], *, apply: bool) -> dict[str, int]:
    """Regrade (GameActuals, GameProjections) pairs; write only when ``apply``."""
    counts = {"changed": 0, "unchanged": 0, "flipped": 0}
    for actual, proj in pairs:
        new = regraded_spread(actual, proj)
        old = actual.spread_correct
        if new == old:
            counts["unchanged"] += 1
            continue
        counts["changed"] += 1
        if old is not None and new is not None:
            counts["flipped"] += 1
        if apply:
            actual.spread_correct = new
    return counts


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
    from app.models.predictions_models import GameActuals, GameProjections

    db = SessionLocal()
    try:
        q = db.query(GameActuals, GameProjections).join(
            GameProjections,
            (GameProjections.date == GameActuals.date)
            & (GameProjections.game_id == GameActuals.game_id),
        )
        if args.start:
            q = q.filter(GameActuals.date >= args.start)
        if args.end:
            q = q.filter(GameActuals.date <= args.end)
        counts = regrade_spreads(q.all(), apply=apply)
        if apply:
            db.commit()
        print(f"{'APPLIED' if apply else 'DRY RUN'}: {counts}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
