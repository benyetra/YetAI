"""CLI for WNBA stored-projection backtest (ATS / O-U / prop ROI)."""

from __future__ import annotations

import argparse
import json
from datetime import date

from app.core.database import SessionLocal
from app.services.etl.wnba.backtest.runner import run_backtest_replay


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WNBA backtest: ATS / totals / props ROI")
    p.add_argument("--start", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    p.add_argument("--end", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    p.add_argument(
        "--quick",
        action="store_true",
        help="Last 45 days only (when --start omitted)",
    )
    p.add_argument(
        "--odds",
        type=int,
        default=-110,
        help="American odds for unit ROI (default -110)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db = SessionLocal()
    try:
        result = run_backtest_replay(
            db,
            start=args.start,
            end=args.end,
            quick=args.quick,
            odds=args.odds,
        )
    finally:
        db.close()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
