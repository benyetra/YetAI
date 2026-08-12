#!/usr/bin/env python3
"""YetAI WNBA backtest entry point.

Replay stored spread / totals / prop projections vs actuals; print ATS, O/U,
and prop ROI at -110 (configurable).

Examples::

    cd backend
    PYTHONPATH=. .venv/bin/python scripts/wnba_backtest.py --quick
    PYTHONPATH=. .venv/bin/python scripts/wnba_backtest.py --start 2025-05-01 --end 2025-10-01
"""

from app.services.etl.wnba.backtest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
