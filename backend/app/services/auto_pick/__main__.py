"""
CLI entry point:
  python -m app.services.auto_pick backtest --start ... --end ...
  python -m app.services.auto_pick dry-run --date YYYY-MM-DD [--now ISO]

``dry-run`` prints what would be published against whatever DATABASE_URL is set.
It never writes (the session is rolled back).
"""

import argparse
import asyncio
import json
from datetime import date, datetime, time

from app.core.database import SessionLocal
from app.services.auto_pick.backtest import run_backtest
from app.services.auto_pick.candidate import EASTERN, to_naive_utc
from app.services.auto_pick.orchestrator import AutoPickOrchestrator, grading_block


def dry_run(db, slate_date: date, now: datetime | None = None, providers=None) -> dict:
    """Would-publish picks + drop summary for ``slate_date`` (default now = 11:00 ET)."""
    if now is None:
        now = to_naive_utc(datetime.combine(slate_date, time(11, 0), tzinfo=EASTERN))
    if providers is None:
        from app.tasks.auto_pick import _build_providers

        providers = _build_providers(db)
    orch = AutoPickOrchestrator(db=db, providers=providers, now=now, dry_run=True)
    result = asyncio.run(orch.run())
    return {
        "now_utc": now.isoformat(),
        "status": result.status.value,
        "would_publish": [
            {
                "selection": p.candidate.selection,
                "league": p.candidate.league,
                "market": p.candidate.market_type.value,
                "odds": p.candidate.market_odds,
                "score": p.score.total,
                "tier": p.tier.value if p.tier else None,
                "commence_time": (
                    p.candidate.commence_time.isoformat()
                    if p.candidate.commence_time
                    else None
                ),
                "grading": grading_block(p.candidate),
            }
            for p in result.picks
        ],
        "dropped": result.dropped_reasons,
    }


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.services.auto_pick")
    sub = p.add_subparsers(dest="cmd", required=True)
    bt = sub.add_parser("backtest")
    bt.add_argument("--start", required=True, type=lambda s: date.fromisoformat(s))
    bt.add_argument("--end", required=True, type=lambda s: date.fromisoformat(s))
    dr = sub.add_parser("dry-run")
    dr.add_argument("--date", required=True, type=date.fromisoformat)
    dr.add_argument("--now", type=datetime.fromisoformat, help="naive UTC ISO time")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.cmd == "backtest":
            result = run_backtest(args.start, args.end, db)
        else:
            result = dry_run(db, args.date, args.now)
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
