#!/usr/bin/env python3
"""Prefetch historical MLB odds into mlb_backtest_cache.db (budget-aware).

The Odds API charges ~20 credits per calendar day (us, h2h+totals).
With a 500-credit plan you can safely prefetch ~20–25 unique dates once,
then rerun backtests without additional historical calls.

Usage (from backend/):

    # List dates + cost for a backtest CSV (no API calls)
    PYTHONPATH=. .venv/bin/python scripts/mlb_backfill_historical_odds.py \\
      --from-csv scripts/mlb_backtest_results/backtest_5492dbc7_2026-05-26.csv \\
      --dry-run

    # Prefetch up to 20 dates (~400 credits max if all uncached)
    PYTHONPATH=. .venv/bin/python scripts/mlb_backfill_historical_odds.py \\
      --from-csv scripts/mlb_backtest_results/backtest_5492dbc7_2026-05-26.csv \\
      --max-dates 20

    # Or sample dates from the same seed as backtest
    PYTHONPATH=. .venv/bin/python scripts/mlb_backfill_historical_odds.py \\
      --seed 42 --n-games 20 --max-dates 20
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
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
    import os

    for name in (".env.production", ".env"):
        path = BACKEND_ROOT / name
        if path.is_file():
            load_dotenv(path)
    public = os.environ.get("DATABASE_PUBLIC_URL", "").strip()
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if public and (not db_url or "railway.internal" in db_url):
        os.environ["DATABASE_URL"] = public


def _dates_from_csv(path: Path) -> list[date]:
    dates: set[date] = set()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        col = "game_date" if "game_date" in (reader.fieldnames or []) else None
        if not col:
            raise SystemExit(f"No game_date column in {path}")
        for row in reader:
            raw = (row.get(col) or "")[:10]
            if raw:
                dates.add(date.fromisoformat(raw))
    return sorted(dates)


def _dates_from_sampler(seed: int, n_games: int) -> list[date]:
    from datetime import date as date_type

    from app.services.etl.mlb.backtest.sampler import BacktestSampler

    sampler = BacktestSampler(
        date_type(2024, 3, 28),
        date_type(2025, 9, 28),
        n_games=n_games,
        seed=seed,
    )
    games = sampler.sample_games()
    return sorted({date.fromisoformat(g.game_date) for g in games})


def main() -> int:
    _bootstrap_env()

    from app.services.etl.mlb.backtest.historical_odds import (
        CREDITS_PER_DATE,
        fetch_historical_odds_snapshot,
        is_date_cached,
        resolve_odds_api_key,
    )

    parser = argparse.ArgumentParser(description="Prefetch historical MLB odds")
    parser.add_argument("--from-csv", type=Path, help="Backtest CSV with game_date")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-games", type=int, default=20)
    parser.add_argument(
        "--max-dates",
        type=int,
        default=20,
        help=f"Max API dates to fetch (≈{CREDITS_PER_DATE} credits each)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan only; no API calls",
    )
    args = parser.parse_args()

    if args.from_csv:
        dates = _dates_from_csv(args.from_csv)
    else:
        dates = _dates_from_sampler(args.seed, args.n_games)

    uncached = [d for d in dates if not is_date_cached(d)]
    to_fetch = uncached[: args.max_dates]
    est_credits = len(to_fetch) * CREDITS_PER_DATE

    logger.info("Unique dates in sample: %s", len(dates))
    logger.info("Already cached: %s", len(dates) - len(uncached))
    logger.info("Would fetch (capped): %s", len(to_fetch))
    logger.info("Estimated credits: %s (max %s/date)", est_credits, CREDITS_PER_DATE)

    if args.dry_run:
        for d in to_fetch:
            logger.info("  fetch %s", d.isoformat())
        return 0

    api_key = resolve_odds_api_key()
    if not api_key:
        logger.error(
            "Set ODDS_API_KEY in backend/.env.production (paid plan required for historical)"
        )
        return 1

    fetched = 0
    for d in to_fetch:
        if is_date_cached(d):
            continue
        result = fetch_historical_odds_snapshot(d, api_key=api_key)
        if result is not None:
            fetched += 1
        else:
            logger.warning("No snapshot stored for %s", d)

    logger.info("Fetched %s new date(s). Re-run backtest without --skip-odds.", fetched)
    return 0 if fetched or not to_fetch else 1


if __name__ == "__main__":
    raise SystemExit(main())
