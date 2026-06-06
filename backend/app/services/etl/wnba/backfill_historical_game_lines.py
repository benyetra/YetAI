"""CLI: backfill pred_wnba_game_lines from Odds API historical snapshots."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from app.services.etl.wnba.historical_game_lines import (
    CREDITS_PER_DATE,
    backfill_from_actuals_window,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill WNBA consensus game lines from Odds API historical odds"
    )
    parser.add_argument("--start", required=True, help="Season start YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Season end YYYY-MM-DD")
    parser.add_argument(
        "--max-dates",
        type=int,
        default=None,
        help=f"Cap API calls (~{CREDITS_PER_DATE} credits/date)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report dates and credit estimate only",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch dates that already have rows in pred_wnba_game_lines",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between Odds API calls",
    )
    args = parser.parse_args(argv)

    result = backfill_from_actuals_window(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        max_dates=args.max_dates,
        dry_run=args.dry_run,
        skip_existing=not args.force,
        delay_seconds=args.delay,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in ("ok", "dry_run") else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
