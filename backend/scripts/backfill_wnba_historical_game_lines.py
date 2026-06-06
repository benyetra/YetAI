#!/usr/bin/env python3
"""Backfill WNBA historical consensus game lines into pred_wnba_game_lines.

Odds API historical endpoint charges ~30 credits per calendar day (us, h2h+spreads+totals).
Dates default to distinct game_date values in pred_wnba_spread_actuals for the window.

Usage (from backend/):

    # Requires prod DATABASE_URL (see backend/.env or Railway dashboard Connect tab)
    export DATABASE_URL='postgresql://...'

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


def main() -> int:
    from scripts._bootstrap_env import bootstrap_env, ensure_database_url

    bootstrap_env(backend_root=BACKEND_ROOT)
    ensure_database_url(backend_root=BACKEND_ROOT)
    from app.services.etl.wnba.backfill_historical_game_lines import main as cli_main

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
