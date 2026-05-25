"""NFL backtest CLI — replay stored predictions vs actuals."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_BASELINE_PATH = (
    BACKEND_ROOT / "tests" / "fixtures" / "nfl_backtest_quick_baseline.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YetAI NFL backtest — QB passing yards and kicker FG made",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Presets:
  --quick     Last 10 (season, week) pairs in range (fast CI / iteration)

Examples:
  PYTHONPATH=. python scripts/nfl_backtest.py --quick
  PYTHONPATH=. python scripts/nfl_backtest.py --season 2024 --start-week 1 --end-week 10
  PYTHONPATH=. python scripts/nfl_backtest.py --quick --write-baseline
        """,
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="NFL season year (default: NFL_SEASON env)",
    )
    parser.add_argument("--start-week", type=int, default=1, help="First week (1-18)")
    parser.add_argument("--end-week", type=int, default=18, help="Last week (1-18)")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Limit to last N season/week pairs",
    )
    parser.add_argument(
        "--max-weeks",
        type=int,
        default=None,
        help="Override week limit when --quick is set",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write summarized metrics to tests/fixtures/nfl_backtest_quick_baseline.json",
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
    from app.core.database import SessionLocal
    from app.services.etl.nfl.backtest.metrics import summarize_nfl_backtest_metrics
    from app.services.etl.nfl.backtest.runner import run_backtest_replay
    from app.services.etl.nfl.nfl_common import get_nfl_season

    season = args.season if args.season is not None else get_nfl_season()
    logger.info(
        "NFL backtest replay season=%s weeks %s..%s (quick=%s)",
        season,
        args.start_week,
        args.end_week,
        args.quick,
    )

    session = SessionLocal()
    try:
        result = run_backtest_replay(
            session=session,
            season=season,
            start_week=args.start_week,
            end_week=args.end_week,
            quick=args.quick,
            max_weeks=args.max_weeks,
        )
    finally:
        session.close()

    summary = summarize_nfl_backtest_metrics(result.scorer)
    if not summary:
        logger.error(
            "No scored rows (qb=%s kicker=%s). Check DATABASE_URL and season/week range.",
            result.rows_scored.get("qb", 0),
            result.rows_scored.get("kicker", 0),
        )
    else:
        logger.info(
            "Scored qb=%s kicker=%s weeks=%s",
            result.rows_scored.get("qb", 0),
            result.rows_scored.get("kicker", 0),
            len(result.weeks_used),
        )
        logger.info("Metrics: %s", summary)

    if args.write_baseline and summary:
        payload = {
            "description": (
                "NFL quick backtest (--quick). Documents tier-table / heuristic "
                "baseline; refresh after intentional model changes."
            ),
            "updated_at": date.today().isoformat(),
            "preset": "quick",
            "season": season,
            "start_week": args.start_week,
            "end_week": args.end_week,
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
