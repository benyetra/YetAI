#!/usr/bin/env python3
"""YetAI NHL backtest entry point.

Replay ``pred_nhl_*_predictions`` rows joined to ``pred_nhl_*_actuals`` and print
MAE / O/U hit rates. CI uses offline unit tests only; this script needs DATABASE_URL.

Examples::

    cd backend
    PYTHONPATH=. python scripts/nhl_backtest.py --quick
    PYTHONPATH=. python scripts/nhl_backtest.py --start-date 2025-11-01 --end-date 2025-12-31
    PYTHONPATH=. python scripts/nhl_backtest.py --quick --write-baseline
"""

from app.services.etl.nhl.backtest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
