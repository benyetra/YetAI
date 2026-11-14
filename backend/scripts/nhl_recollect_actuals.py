#!/usr/bin/env python3
"""Re-collect NHL actuals (team totals, goalies, player shots, team shots) for a date range.

Why: actuals collected before the NHL-2 fix carry blank team names and goalie
rows matched by name, so nothing graded. This re-pulls each date's boxscores from
the public NHL API and upserts the rows (names, prediction mirror,
recommendation_correct). Idempotent: a second run reports 0 inserted / 0 updated.

Dry run is the default (rolls back); pass --apply to write.

Usage (production URL via Railway resolver):
  cd backend
  export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
  PYTHONPATH=. python3 scripts/nhl_recollect_actuals.py --start 2026-10-01 --end 2026-11-12
  PYTHONPATH=. python3 scripts/nhl_recollect_actuals.py --start 2026-10-01 --end 2026-11-12 --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_day, required=True, help="First game date")
    parser.add_argument(
        "--end", type=_day, help="Last game date (default: yesterday, server date)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default is a dry run)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Explicit dry run (the default)"
    )
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")
    end = args.end or date.today() - timedelta(days=1)
    if end < args.start:
        parser.error("--end is before --start")

    from app.services.etl.nhl._db import close_session, init_session
    from app.services.etl.nhl.collect_goalie_actuals import update_goalie_actuals
    from app.services.etl.nhl.collect_player_shots_actuals import (
        update_player_shots_actuals,
    )
    from app.services.etl.nhl.collect_team_shots_actuals import (
        update_team_shots_actuals,
    )
    from app.services.etl.nhl.collect_team_totals_actuals import (
        update_team_totals_actuals,
    )

    collectors = [
        ("team_totals", update_team_totals_actuals),
        ("goalies", update_goalie_actuals),
        ("player_shots", update_player_shots_actuals),
        ("team_shots", update_team_shots_actuals),
    ]
    mode = "APPLY" if args.apply else "DRY RUN"
    logger.info("NHL actuals re-collect %s..%s (%s)", args.start, end, mode)

    totals = {name: [0, 0] for name, _ in collectors}
    init_session()
    try:
        day = args.start
        while day <= end:
            for name, fn in collectors:
                r = fn(day, commit=args.apply)
                totals[name][0] += r["rows_inserted"]
                totals[name][1] += r["rows_updated"]
                if r["rows_inserted"] or r["rows_updated"]:
                    logger.info(
                        "%s %s: %s inserted, %s updated (%s games)",
                        day,
                        name,
                        r["rows_inserted"],
                        r["rows_updated"],
                        r["games_processed"],
                    )
            day += timedelta(days=1)
    finally:
        close_session()

    for name, (ins, upd) in totals.items():
        logger.info("%s: %s inserted, %s updated", name, ins, upd)
    if not args.apply:
        logger.info("Dry run only; re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
