#!/usr/bin/env python3
"""Prefetch historical NFL player_pass_yds into a local cache + lines index.

Credit model (The Odds API paid plan):
  - historical events slate / gameday ≈ 1 credit
  - historical event odds (regions=us, markets=player_pass_yds) ≈ 10 credits

Everything is SQLite-cached (``scripts/nfl_odds_cache.db``). Re-runs cost ~0.

Examples (from backend/)::

    export ODDS_API_KEY=...
    # Plan only
    PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py \\
      --seasons 2023,2024 --dry-run

    # Fetch under budget (recommended first pass)
    PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py \\
      --seasons 2023,2024 --max-credits 5500

    # Fill 2025 gaps after
    PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py \\
      --seasons 2025 --max-credits 2000

    # Assign team abbr from pred_qb_actuals (needs DATABASE_URL)
    PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --assign-teams
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _bootstrap_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for name in (".env.production", ".env"):
        path = BACKEND_ROOT / name
        if path.is_file():
            load_dotenv(path)


def main() -> int:
    _bootstrap_env()
    from app.services.etl.nfl.historical_pass_yds_odds import (
        CREDITS_EVENTS,
        CREDITS_PROPS,
        assign_teams_from_actuals,
        backfill_pass_yds_odds,
        resolve_odds_api_key,
    )

    parser = argparse.ArgumentParser(
        description="Backfill historical NFL pass-yards props (credit-aware)"
    )
    parser.add_argument(
        "--seasons",
        type=str,
        default="2023,2024,2025",
        help="Comma-separated seasons",
    )
    parser.add_argument(
        "--max-credits",
        type=int,
        default=5500,
        help=f"Stop before exceeding this spend "
        f"(events={CREDITS_EVENTS}, props={CREDITS_PROPS}/game)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Rebuild index from SQLite cache; no API calls",
    )
    parser.add_argument(
        "--assign-teams",
        action="store_true",
        help="Fill team_abbr on index rows from pred_qb_actuals",
    )
    parser.add_argument(
        "--rebuild-from-cache",
        action="store_true",
        help="Rewrite pass_yds_lines.json from SQLite cache only (0 credits)",
    )
    parser.add_argument(
        "--no-skip-indexed",
        action="store_true",
        help="Re-fetch props even when event already in index",
    )
    args = parser.parse_args()
    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]

    if args.assign_teams:
        if not os.getenv("DATABASE_URL", "").strip():
            logger.error("DATABASE_URL required for --assign-teams")
            return 2
        out = assign_teams_from_actuals(seasons=seasons)
        print(json.dumps({"status": "ok", "assign_teams": out}, indent=2))
        return 0

    if args.rebuild_from_cache:
        from app.services.etl.nfl.historical_pass_yds_odds import (
            rebuild_lines_index_from_cache,
        )

        out = rebuild_lines_index_from_cache(seasons=seasons)
        print(json.dumps({"status": "ok", "rebuild": out}, indent=2, default=str))
        return 0

    if not args.dry_run and not args.cache_only and not resolve_odds_api_key():
        logger.error("Set ODDS_API_KEY (paid plan required for historical props)")
        return 1

    report = backfill_pass_yds_odds(
        seasons=seasons,
        max_credits=args.max_credits,
        cache_only=args.cache_only,
        dry_run=args.dry_run,
        skip_indexed=not args.no_skip_indexed,
    )
    print(json.dumps(report, indent=2, default=str))
    if args.dry_run:
        return 0
    return 0 if report.get("credits_spent", 0) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
