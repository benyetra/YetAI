#!/usr/bin/env python3
"""Retrain the MLB strikeout over/under classifier (CLI wrapper).

Prod: prefer POST /api/admin/celery/ml-ops/retrain-strikeouts or enqueue-task on worker.

Usage (from backend/, needs DATABASE_URL on prod for real training):

    PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py --dry-run
    PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrain MLB strikeout classifier")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate counts and training rows only",
    )
    args = parser.parse_args()

    from app.services.etl.mlb.strikeout_training import run_retrain_strikeouts

    try:
        manifest = run_retrain_strikeouts(dry_run=args.dry_run)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
