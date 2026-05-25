"""CLI: ``python -m app.services.etl.nba.ml_training --stat points --start ...``"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.etl.nba.ml_training.run_train_props import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train NBA XGB prop model")
    parser.add_argument(
        "--stat",
        required=True,
        choices=NBA_ML_CONFIG.supported_stats,
        help="Prop stat to train",
    )
    parser.add_argument(
        "--start", required=True, help="Training window start YYYY-MM-DD"
    )
    parser.add_argument("--end", required=True, help="Training window end YYYY-MM-DD")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload to s3://yetibets/nba/ml_models/ after MAE gate passes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build dataset and report row counts only",
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            args.stat,
            season_start=date.fromisoformat(args.start),
            season_end=date.fromisoformat(args.end),
            upload=args.upload,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    status = result.get("status")
    if status in ("ok", "dry_run"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
