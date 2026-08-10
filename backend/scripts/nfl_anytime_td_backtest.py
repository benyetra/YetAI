#!/usr/bin/env python3
"""NFL anytime-TD backtest entry point.

Offline ``--quick`` uses a fixed synthetic sample (no DATABASE_URL / Odds).
Full replay joins stored predictions to actuals when DATABASE_URL is set.

Examples::

    cd backend
    PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick
    PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick --write-metrics
    PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --season 2024 --start-week 1 --end-week 8
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YetAI NFL anytime-TD backtest — offline quick smoke or DB replay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use fixed synthetic sample (default when no season/week DB replay)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="NFL season year for DB replay (default: NFL_SEASON env)",
    )
    parser.add_argument("--start-week", type=int, default=1, help="First week (1-18)")
    parser.add_argument("--end-week", type=int, default=18, help="Last week (1-18)")
    parser.add_argument(
        "--max-weeks",
        type=int,
        default=None,
        help="Limit weeks when --quick DB replay is combined with stored rows",
    )
    parser.add_argument(
        "--write-metrics",
        action="store_true",
        help="Write metrics to backend/models/nfl/anytime_td_metrics.json",
    )
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=BACKEND_ROOT / "models" / "nfl" / "anytime_td_metrics.json",
        help="Metrics JSON output path for --write-metrics",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print metrics payload as JSON to stdout",
    )
    parser.add_argument(
        "--check-gate",
        action="store_true",
        help="Exit 1 when metrics fail passes_gate vs artifact gate thresholds",
    )
    return parser.parse_args(argv)


def run_backtest(args: argparse.Namespace) -> dict:
    from app.services.etl.nfl.anytime_td_backtest import (
        DEFAULT_GATE_BASELINES,
        passes_gate,
        run_backtest_replay,
        run_quick_backtest,
        write_metrics_artifact,
    )

    use_quick = args.quick or args.season is None

    if use_quick and args.season is None:
        payload = run_quick_backtest()
        metrics = payload["metrics"]
        gate = payload.get("gate", DEFAULT_GATE_BASELINES)
        result = {
            "preset": payload["preset"],
            "metrics": metrics,
            "gate": gate,
            "passes_gate": payload.get("passes_gate", passes_gate(metrics, gate)),
        }
    else:
        from app.core.database import SessionLocal

        session = SessionLocal()
        try:
            replay = run_backtest_replay(
                session=session,
                season=args.season,
                start_week=args.start_week,
                end_week=args.end_week,
                quick=args.quick,
                max_weeks=args.max_weeks,
            )
        finally:
            session.close()
        metrics = replay.metrics
        gate = dict(DEFAULT_GATE_BASELINES)
        result = {
            "preset": "db_replay",
            "metrics": metrics,
            "gate": gate,
            "passes_gate": passes_gate(metrics, gate),
            "weeks_used": replay.weeks_used,
            "rows_scored": replay.rows_scored,
        }

    if not metrics.get("n_graded"):
        logger.error("No graded anytime-TD rows; check DATABASE_URL or use --quick.")
    else:
        logger.info(
            "Anytime-TD backtest n=%s brier=%s baseline=%s passes_gate=%s",
            metrics.get("n_graded"),
            metrics.get("brier"),
            metrics.get("baseline_brier"),
            result.get("passes_gate"),
        )

    if args.write_metrics and metrics.get("n_graded"):
        path = write_metrics_artifact(
            metrics,
            path=args.metrics_path,
            preset=str(result.get("preset", "quick")),
            gate=result.get("gate"),
        )
        logger.info("Wrote metrics artifact to %s", path)

    if args.json:
        print(json.dumps(result, indent=2))

    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    result = run_backtest(args)
    metrics = result.get("metrics") or {}
    if not metrics.get("n_graded"):
        return 1
    if args.check_gate and not result.get("passes_gate"):
        logger.error("Gate check failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
