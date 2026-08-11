#!/usr/bin/env python3
"""Backfill NFL QB + kicker actuals into Railway Postgres.

Examples:
  export DATABASE_URL=...
  PYTHONPATH=. python scripts/nfl_backfill_actuals.py --kickers --season 2025
  PYTHONPATH=. python scripts/nfl_backfill_actuals.py --qb --seasons 2023,2024,2025
  PYTHONPATH=. python scripts/nfl_backfill_actuals.py --all
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill NFL actuals tables")
    parser.add_argument("--kickers", action="store_true")
    parser.add_argument("--qb", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--season", type=int, default=2025, help="Kicker season")
    parser.add_argument(
        "--seasons",
        type=str,
        default="2023,2024,2025",
        help="Comma-separated QB seasons",
    )
    parser.add_argument("--start-week", type=int, default=1)
    parser.add_argument("--end-week", type=int, default=18)
    args = parser.parse_args()

    if not os.getenv("DATABASE_URL", "").strip():
        print(json.dumps({"status": "error", "error": "DATABASE_URL required"}))
        return 2

    do_kickers = args.kickers or args.all
    do_qb = args.qb or args.all
    if not do_kickers and not do_qb:
        parser.error("pass --kickers, --qb, or --all")

    from app.services.etl.nfl._db import close_session, init_session

    report: dict[str, Any] = {"status": "ok"}
    init_session()
    try:
        if do_kickers:
            from app.services.etl.nfl.collect_kicker_actuals import (
                backfill_kicker_actuals,
            )

            report["kickers"] = backfill_kicker_actuals(
                season=args.season,
                start_week=args.start_week,
                end_week=args.end_week,
            )
        if do_qb:
            from app.services.etl.nfl.backfill_qb_actuals import backfill_qb_actuals

            seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
            report["qb"] = backfill_qb_actuals(
                seasons=seasons,
                start_week=args.start_week,
                end_week=args.end_week,
            )
    finally:
        close_session()

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
