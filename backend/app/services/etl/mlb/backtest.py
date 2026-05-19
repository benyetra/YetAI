#!/usr/bin/env python
"""YetiBets MLB Backtesting Engine — CLI Entry Point.

Runs projection models against random past games and measures accuracy
against actual outcomes. Produces reproducible accuracy reports.

Usage:
    python scripts/mlb/backtest.py --n-games 100 --seed 42
    python scripts/mlb/backtest.py --quick
    python scripts/mlb/backtest.py --full-season --start-date 2024-04-01 --end-date 2024-09-28
    python scripts/mlb/backtest.py --compare <backtest_id>

REQ-BT-056 through REQ-BT-064.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Import from the package — works because this file is run directly,
# so scripts.mlb.backtest resolves to the package directory.
from app.services.etl.mlb.backtest.cli import main

if __name__ == '__main__':
    main()
