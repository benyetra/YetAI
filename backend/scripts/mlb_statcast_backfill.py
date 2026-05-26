#!/usr/bin/env python3
"""Monthly Statcast pitch backfill to S3/local parquet partitions."""

from __future__ import annotations

import argparse
import logging
import sys

from app.services.etl.mlb.statcast_ingest.backfill import backfill_month

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MLB_MONTHS = range(3, 11)  # Mar–Oct


def main() -> int:
    p = argparse.ArgumentParser(
        description="Backfill Statcast pitch parquet partitions"
    )
    p.add_argument("--start-year", type=int, default=2018)
    p.add_argument("--end-year", type=int)
    p.add_argument("--season", type=int)
    p.add_argument("--month", type=int)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    failures: list[str] = []

    if args.season and args.month:
        seasons_months = [(args.season, args.month)]
    elif args.season:
        seasons_months = [(args.season, m) for m in MLB_MONTHS]
    else:
        end = args.end_year or args.start_year
        seasons_months = [
            (y, m) for y in range(args.start_year, end + 1) for m in MLB_MONTHS
        ]

    for season, month in seasons_months:
        try:
            uri = backfill_month(season, month, force=args.force)
            logger.info("season=%s month=%02d → %s", season, month, uri)
        except Exception as exc:
            logger.error("failed season=%s month=%02d: %s", season, month, exc)
            failures.append(f"{season}-{month:02d}")

    if failures:
        logger.error("failed months: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
