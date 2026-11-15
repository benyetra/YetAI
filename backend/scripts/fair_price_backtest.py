#!/usr/bin/env python3
"""Fair-price backtest over odds_line_snapshots (live capture + historical backfill).

Usage (from backend/):

    PYTHONPATH=. .venv/bin/python scripts/fair_price_backtest.py --from 2025-11-01 \\
        --to 2026-04-12 --markets player_rebounds,player_assists --out DIR \\
        [--min-ev 0.05] [--min-books 3] [--method power] [--seed 0] [--placebo-runs 20]

Reads DATABASE_URL. Writes DIR/report.md, DIR/summary.json (byte-identical for the same data
and arguments) and DIR/flags.csv; prints the verdict and the overall table.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts._bootstrap_env import bootstrap_env  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    ap.add_argument("--to", dest="end", required=True, type=date.fromisoformat)
    ap.add_argument("--markets", default="player_rebounds,player_assists")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-ev", type=float, default=0.05)
    ap.add_argument("--min-books", type=int, default=3)
    ap.add_argument("--method", default="power")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--placebo-runs", type=int, default=20)
    a = ap.parse_args(argv)

    bootstrap_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("no DATABASE_URL configured")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.services.fair_price import backtest as bt
    from app.services.fair_price.flags import FlagRule

    with sessionmaker(bind=create_engine(url))() as s:
        quotes = bt.load_snapshots(s, a.markets.split(","), a.start, a.end)
        key_to_id, dropped = bt.load_player_keys(s)
        box = bt.load_box(s, a.start, a.end)
    params = bt.Params(
        rule=FlagRule(min_ev=a.min_ev, min_books=a.min_books, method=a.method),
        seed=a.seed,
        placebo_runs=a.placebo_runs,
    )
    res = bt.run_backtest(quotes, key_to_id, box, params, dropped_keys=dropped)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(bt.summary_json(res["summary"]))
    (out / "flags.csv").write_text(bt.flags_csv(res["flags"]))
    (out / "report.md").write_text(bt.report_md(res["summary"]))
    print(f"VERDICT: {res['summary']['verdict']}")
    print(bt.report_md(res["summary"]).split("## By market")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
