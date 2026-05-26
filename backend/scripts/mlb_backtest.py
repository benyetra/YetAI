#!/usr/bin/env python3
"""Run the MLB backtest CLI (YetAI port of YetiBets scripts/mlb/backtest.py).

Usage (from backend/):

    PYTHONPATH=. python scripts/mlb_backtest.py --quick
    PYTHONPATH=. python scripts/mlb_backtest.py --n-games 50 --seed 42
    PYTHONPATH=. python scripts/mlb_backtest.py --compare <run_id_prefix>
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _bootstrap_database_url() -> None:
    """Prefer a public Postgres URL for local backtests (Phase 5 profiles)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    for name in (".env.production", ".env"):
        path = BACKEND_ROOT / name
        if path.is_file():
            load_dotenv(path)

    public = os.environ.get("DATABASE_PUBLIC_URL", "").strip()
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if public and (not db_url or "railway.internal" in db_url):
        os.environ["DATABASE_URL"] = public


_bootstrap_database_url()

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

from app.services.etl.mlb.backtest.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
