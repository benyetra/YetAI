"""
CLI entry point: python -m app.services.auto_pick backtest --start ... --end ...
"""
import argparse
import json
from datetime import date

from app.core.database import SessionLocal
from app.services.auto_pick.backtest import run_backtest


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.services.auto_pick")
    sub = p.add_subparsers(dest="cmd", required=True)
    bt = sub.add_parser("backtest")
    bt.add_argument("--start", required=True, type=lambda s: date.fromisoformat(s))
    bt.add_argument("--end", required=True, type=lambda s: date.fromisoformat(s))
    args = p.parse_args()

    db = SessionLocal()
    try:
        result = run_backtest(args.start, args.end, db)
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
