#!/usr/bin/env python3
"""YetAI NFL backtest entry point.

Replay ``pred_qb_*`` and kicker predictions vs actuals; print MAE / O/U rates.
CI uses offline unit tests only; this script needs DATABASE_URL.

Examples::

    cd backend
    PYTHONPATH=. python scripts/nfl_backtest.py --quick
    PYTHONPATH=. python scripts/nfl_backtest.py --season 2024 --start-week 1 --end-week 8
    PYTHONPATH=. python scripts/nfl_backtest.py --quick --write-baseline
"""

from app.services.etl.nfl.backtest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
