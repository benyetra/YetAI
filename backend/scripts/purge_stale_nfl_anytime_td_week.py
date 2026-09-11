#!/usr/bin/env python3
"""One-shot purge of stale NFL anytime-TD week rows older than the latest run.

Use for immediate prod relief when a successful projector upsert left prior
same-season/week players on the board (wrong TEAM after trades / depth
changes). Prefer re-running the projector after the slate-replace deploy;
this script is the manual fallback when coordinator has Railway DB access.

Examples:

  # Dry-run season=2026 week=1
  PYTHONPATH=. python scripts/purge_stale_nfl_anytime_td_week.py \\
      --season 2026 --week 1 --dry-run

  # Apply
  PYTHONPATH=. python scripts/purge_stale_nfl_anytime_td_week.py \\
      --season 2026 --week 1
"""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--week", type=int, required=True)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts / sample rows without deleting",
    )
    p.add_argument(
        "--limit-sample",
        type=int,
        default=10,
        help="Sample size of stale rows to print (dry-run or apply)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from app.core.database import SessionLocal
    from app.models.predictions_models import NFLAnytimeTDPredictions
    from sqlalchemy import func

    db = SessionLocal()
    try:
        latest = (
            db.query(func.max(NFLAnytimeTDPredictions.prediction_date))
            .filter(
                NFLAnytimeTDPredictions.season == args.season,
                NFLAnytimeTDPredictions.week == args.week,
            )
            .scalar()
        )
        if latest is None:
            print(
                f"No rows for season={args.season} week={args.week}; nothing to purge."
            )
            return 0

        stale_q = db.query(NFLAnytimeTDPredictions).filter(
            NFLAnytimeTDPredictions.season == args.season,
            NFLAnytimeTDPredictions.week == args.week,
            NFLAnytimeTDPredictions.prediction_date < latest,
        )
        stale_count = stale_q.count()
        fresh_count = (
            db.query(NFLAnytimeTDPredictions)
            .filter(
                NFLAnytimeTDPredictions.season == args.season,
                NFLAnytimeTDPredictions.week == args.week,
                NFLAnytimeTDPredictions.prediction_date == latest,
            )
            .count()
        )
        print(
            f"season={args.season} week={args.week} "
            f"latest_prediction_date={latest.isoformat()} "
            f"fresh={fresh_count} stale={stale_count}"
        )
        sample = (
            stale_q.order_by(NFLAnytimeTDPredictions.player_name)
            .limit(args.limit_sample)
            .all()
        )
        for row in sample:
            print(
                f"  stale: {row.player_name} | {row.position} | "
                f"{row.team_name} | pred_date={row.prediction_date}"
            )
        if args.dry_run:
            print("dry-run: no rows deleted")
            return 0
        if stale_count == 0:
            print("nothing to delete")
            return 0
        deleted = stale_q.delete(synchronize_session=False)
        db.commit()
        print(f"deleted={deleted}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
