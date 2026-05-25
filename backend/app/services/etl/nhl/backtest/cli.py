"""NHL backtest CLI — replay stored predictions vs actuals."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_START = "2025-10-01"
DEFAULT_END = "2026-04-30"
BACKEND_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_BASELINE_PATH = (
    BACKEND_ROOT / "tests" / "fixtures" / "nhl_backtest_quick_baseline.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YetAI NHL backtest — goalie saves, player SOG, team totals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Presets:
  --quick     Last 10 slates in range (fast CI / iteration)

Examples:
  PYTHONPATH=. python scripts/nhl_backtest.py --quick
  PYTHONPATH=. python scripts/nhl_backtest.py --start-date 2025-11-01 --end-date 2025-12-31
  PYTHONPATH=. python scripts/nhl_backtest.py --quick --write-baseline
        """,
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=DEFAULT_START,
        help="Start of replay window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=DEFAULT_END,
        help="End of replay window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help=f"Limit to last N slates (default {10} unique game dates)",
    )
    parser.add_argument(
        "--max-slates",
        type=int,
        default=None,
        help="Override slate limit when --quick is set",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write summarized metrics to tests/fixtures/nhl_backtest_quick_baseline.json",
    )
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Baseline JSON path for --write-baseline",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print summarized metrics as JSON to stdout",
    )
    return parser.parse_args(argv)


def run_backtest(args: argparse.Namespace) -> dict:
    """Execute DB replay and return summarized metrics."""
    from app.core.database import SessionLocal
    from app.services.etl.nhl.backtest.metrics import summarize_nhl_backtest_metrics
    from app.services.etl.nhl.backtest.runner import run_backtest_replay

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)

    logger.info("NHL backtest replay %s .. %s (quick=%s)", start, end, args.quick)

    session = SessionLocal()
    try:
        result = run_backtest_replay(
            session=session,
            start_date=start,
            end_date=end,
            quick=args.quick,
            max_slates=args.max_slates,
        )
    finally:
        session.close()

    summary = summarize_nhl_backtest_metrics(result.scorer)
    if not summary:
        logger.error(
            "No scored rows (goalie=%s sog=%s totals=%s). Check DATABASE_URL and date range.",
            result.rows_scored.get("goalie", 0),
            result.rows_scored.get("sog", 0),
            result.rows_scored.get("totals", 0),
        )
    else:
        logger.info(
            "Scored goalie=%s sog=%s totals=%s slates=%s",
            result.rows_scored.get("goalie", 0),
            result.rows_scored.get("sog", 0),
            result.rows_scored.get("totals", 0),
            len(result.slates_used),
        )
        logger.info("Metrics: %s", summary)

    if args.write_baseline and summary:
        payload = {
            "description": (
                "NHL quick backtest (--quick, limited slates). Refresh via "
                "scripts/update_nhl_backtest_baseline.py after intentional model changes."
            ),
            "updated_at": date.today().isoformat(),
            "preset": "quick",
            "start_date": args.start_date,
            "end_date": args.end_date,
            "metrics": summary,
        }
        args.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote baseline to %s", args.baseline_path)

    if args.json and summary:
        print(json.dumps(summary, indent=2))

    return summary


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    summary = run_backtest(args)
    return 0 if summary else 1


def main_entry() -> None:
    raise SystemExit(main())
