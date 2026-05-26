#!/usr/bin/env python3
"""Rebuild MLB batter/pitcher profile snapshots for an as-of date."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from app.services.etl.mlb.profiles.profile_builder import rebuild_all_profiles

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser(description="Rebuild MLB profile snapshots")
    p.add_argument("--as-of", type=str, help="YYYY-MM-DD (default: today)")
    p.add_argument(
        "--prefix",
        type=str,
        default=None,
        help="Override MLB_STATCAST_S3_PREFIX for pitch parquet",
    )
    args = p.parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    counts = rebuild_all_profiles(as_of_date=as_of, prefix=args.prefix)
    logger.info("rebuild complete as_of=%s counts=%s", as_of, counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
