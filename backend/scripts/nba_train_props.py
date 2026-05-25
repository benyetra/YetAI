#!/usr/bin/env python3
"""Retrain an NBA XGB prop model (points / rebounds / assists).

Prod: prefer workflow_dispatch (``.github/workflows/nba-train-props.yml``).

Usage (from ``backend/``, needs ``DATABASE_URL`` for real training):

    PYTHONPATH=. python scripts/nba_train_props.py --stat points --start 2024-10-01 --end 2025-04-30 --dry-run
    PYTHONPATH=. python scripts/nba_train_props.py --stat points --start 2024-10-01 --end 2025-04-30 --upload
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.etl.nba.ml_training.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
