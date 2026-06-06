#!/usr/bin/env python3
"""Backfill WNBA historical consensus game lines into pred_wnba_game_lines.

Odds API historical endpoint charges ~30 credits per calendar day (us, h2h+spreads+totals).
Dates default to distinct game_date values in pred_wnba_spread_actuals for the window.

Usage (from backend/):

    # Credit estimate only
    PYTHONPATH=. .venv/bin/python scripts/backfill_wnba_historical_game_lines.py \\
      --start 2024-05-01 --end 2025-10-01 --dry-run

    # First 25 missing dates (~750 credits max)
    PYTHONPATH=. .venv/bin/python scripts/backfill_wnba_historical_game_lines.py \\
      --start 2024-05-01 --end 2025-10-01 --max-dates 25

    # Live slate (current + upcoming games)
    PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.update_game_lines
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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
    if public and (
        not db_url
        or "railway.internal" in db_url
        or ":port" in db_url
        or "@host:" in db_url
    ):
        os.environ["DATABASE_URL"] = public


def main() -> int:
    _bootstrap_env()
    from app.services.etl.wnba.backfill_historical_game_lines import main as cli_main

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
