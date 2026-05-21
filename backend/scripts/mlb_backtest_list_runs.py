#!/usr/bin/env python3
"""List saved MLB backtest JSON runs (newest first).

Usage (from backend/):
  PYTHONPATH=. python scripts/mlb_backtest_list_runs.py
  PYTHONPATH=. python scripts/mlb_backtest_list_runs.py --limit 5
  PYTHONPATH=. python scripts/mlb_backtest_list_runs.py --compare-prefix d4bc728e
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="List MLB backtest run JSON files")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--compare-prefix",
        help="Show full id for runs matching this prefix (for mlb_backtest.py --compare)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from app.services.etl.mlb.backtest.persistence import list_runs, load_run

    if args.compare_prefix:
        payload = load_run(args.compare_prefix)
        if not payload:
            print(f"No run matching prefix: {args.compare_prefix}")
            return 1
        print(json.dumps(payload, indent=2, default=str))
        return 0

    runs = list_runs(limit=args.limit)
    if args.json:
        print(json.dumps(runs, indent=2))
        return 0

    if not runs:
        print("No runs in scripts/mlb_backtest_results/runs/")
        print("Run: PYTHONPATH=. python scripts/mlb_backtest.py --quick")
        return 0

    print(f"{'id':<38} {'run_date':<22} {'n_games':>7} {'ml_acc':>7} {'brier':>7}")
    for row in runs:
        print(
            f"{row.get('id','')[:36]:<38} "
            f"{str(row.get('run_date',''))[:22]:<22} "
            f"{row.get('n_games') or 0:>7} "
            f"{(row.get('ml_accuracy') or 0):>7.1%} "
            f"{(row.get('brier_score') or 0):>7.3f}"
        )
    print(
        "\nCompare: PYTHONPATH=. python scripts/mlb_backtest.py --compare <id_prefix>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
