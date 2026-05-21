#!/usr/bin/env python3
"""Orchestrate dingerParlay HR training artifact rebuild (CLI wrapper).

Prod: POST /api/admin/celery/ml-ops/hr-rebuild with JSON body.

Usage (from backend/):

    PYTHONPATH=. python scripts/mlb_hr_rebuild.py --list-stages
    PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage build-training --season 2024 --use-existing-s3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = BACKEND_ROOT / "scripts" / "mlb_hr_rebuild_manifest.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    from app.services.etl.mlb.hr_rebuild_runner import STAGES, run_hr_rebuild_stage

    parser = argparse.ArgumentParser(description="dingerParlay HR rebuild orchestrator")
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--holdout-date", default="2024-07-01")
    parser.add_argument("--use-existing-s3", action="store_true")
    parser.add_argument(
        "--run-through",
        choices=STAGES,
        metavar="STAGE",
        help="Run this stage and all following stages",
    )
    args = parser.parse_args()

    if args.list_stages:
        for s in STAGES:
            print(s)
        return 0

    stage = args.run_through or args.stage
    if not stage:
        parser.error("Pass --stage or --run-through")

    stages = STAGES[STAGES.index(stage) :]
    merged: dict = {"stages": list(stages), "season": args.season}
    for st in stages:
        logger.info("=== stage: %s ===", st)
        merged.update(
            run_hr_rebuild_stage(
                st,
                season=args.season,
                holdout_date=args.holdout_date,
                use_existing_s3=args.use_existing_s3,
                backend_root=str(BACKEND_ROOT),
            )
        )

    MANIFEST_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(json.dumps(merged, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
