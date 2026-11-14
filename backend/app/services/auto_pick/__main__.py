"""
CLI entry point:
  python -m app.services.auto_pick backtest --start ... --end ...
  python -m app.services.auto_pick dry-run --date YYYY-MM-DD [--now ISO]
  python -m app.services.auto_pick gate [--now ISO]

``dry-run`` prints what would be published against whatever DATABASE_URL is set.
``gate`` prints the record gate's decision per (league, market, stat) key: bet record,
projection prior, combined shrunk ROI, withheld or open. Both never write (the session
is rolled back).
"""

import argparse
import asyncio
import json
from datetime import date, datetime, time, timezone

from app.core.database import SessionLocal
from app.services.auto_pick.backtest import run_backtest
from app.services.auto_pick.candidate import EASTERN, to_naive_utc
from app.services.auto_pick.orchestrator import AutoPickOrchestrator, grading_block
from app.services.auto_pick.record_gate import gate_report


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


def print_gate_report(rows: list[dict]) -> None:
    print(
        f"{'key':34} {'bets':>5} {'units':>7} {'prior':>9} {'hit%':>6} "
        f"{'n_eff':>6} {'ROI':>8} {'min_edge':>8}  gate"
    )
    for r in rows:
        hit = "-" if r["prior_hit_rate"] is None else f"{r['prior_hit_rate']:.1%}"
        prior = f"{r['proj_hits']}/{r['proj_n']}"
        qe = "-" if r["qualifying_edge"] is None else f"{r['qualifying_edge']:.2f}"
        print(
            f"{r['key']:34} {r['bet_n']:>5} {r['bet_units']:>7} {prior:>9} {hit:>6} "
            f"{r['n_eff']:>6} {r['shrunk_roi']:>8.2%} {qe:>8}  "
            f"{r['state']}"
        )


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.services.auto_pick")
    sub = p.add_subparsers(dest="cmd", required=True)
    bt = sub.add_parser("backtest")
    bt.add_argument("--start", required=True, type=lambda s: date.fromisoformat(s))
    bt.add_argument("--end", required=True, type=lambda s: date.fromisoformat(s))
    dr = sub.add_parser("dry-run")
    dr.add_argument("--date", required=True, type=date.fromisoformat)
    dr.add_argument("--now", type=datetime.fromisoformat, help="naive UTC ISO time")
    gt = sub.add_parser("gate")
    gt.add_argument("--now", type=datetime.fromisoformat, help="naive UTC ISO time")
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.cmd == "gate":
            now = args.now or datetime.now(timezone.utc).replace(tzinfo=None)
            print_gate_report(gate_report(db, now))
            return
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
