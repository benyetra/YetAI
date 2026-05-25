#!/usr/bin/env python3
"""Refresh committed NHL quick-backtest CI baseline (requires DATABASE_URL).

Runs ``scripts/nhl_backtest.py --quick --write-baseline``. Use after an intentional
model change that should become the new regression reference.

Example::

    cd backend
    PYTHONPATH=. python scripts/update_nhl_backtest_baseline.py
    pytest tests/test_nhl_backtest_regression.py -q
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_PATH = (
    BACKEND_ROOT / "tests" / "fixtures" / "nhl_backtest_quick_baseline.json"
)


def main(argv: list[str] | None = None) -> int:
    from app.services.etl.nhl.backtest.cli import parse_args, run_backtest

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Baseline JSON path",
    )
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print metrics only")
    extra = parser.parse_args(argv)

    cli_argv = ["--quick", "--write-baseline", "--baseline-path", str(extra.output)]
    if extra.start_date:
        cli_argv.extend(["--start-date", extra.start_date])
    if extra.end_date:
        cli_argv.extend(["--end-date", extra.end_date])
    if extra.dry_run:
        cli_argv.append("--json")

    args = parse_args(cli_argv)
    if extra.dry_run:
        args.write_baseline = False

    summary = run_backtest(args)
    if not summary:
        logger.error("Backtest produced no metrics; baseline not updated.")
        return 1
    if extra.dry_run:
        import json

        print(json.dumps(summary, indent=2))
    else:
        logger.info("Baseline written to %s", extra.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
