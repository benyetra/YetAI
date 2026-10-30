"""CLI wrapper for backfill_shooting_columns.run()."""

from __future__ import annotations

import argparse
import json

from app.services.etl.wnba.backfill_shooting_columns import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill WNBA eFG/TS columns")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(dry_run=args.dry_run), indent=2))
