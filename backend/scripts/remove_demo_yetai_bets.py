#!/usr/bin/env python3
"""
Mark legacy demo YetAI bets as rejected so they never appear on /predictions.

Usage (from backend/, with prod DATABASE_URL in env or backend/.env):
  export DATABASE_URL='postgresql://...'   # Railway → Postgres → Connect
  PYTHONPATH=. .venv/bin/python scripts/remove_demo_yetai_bets.py --dry-run
  PYTHONPATH=. .venv/bin/python scripts/remove_demo_yetai_bets.py

Do not use bare ``python3`` — it lacks sqlalchemy and other deps.
"""

from __future__ import annotations

import argparse
import sys

try:
    from app.core.database import SessionLocal
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        print(
            "Missing dependencies. Run with the backend venv:\n"
            "  cd backend && PYTHONPATH=. .venv/bin/python scripts/remove_demo_yetai_bets.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise
from app.models.database_models import YetAIBet
from app.services.yetai_bets_demo import DEMO_MATCHUP_TITLES, is_demo_yetai_bet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = db.query(YetAIBet).all()
        targets = [b for b in rows if is_demo_yetai_bet(b)]
        if not targets:
            print(f"No demo bets found (titles: {sorted(DEMO_MATCHUP_TITLES)})")
            return 0
        for bet in targets:
            print(
                f"{'DRY' if args.dry_run else 'REJECT'} {bet.id[:8]} "
                f"title={bet.title!r} status={bet.status}"
            )
            if not args.dry_run:
                bet.status = "rejected"
        if not args.dry_run:
            db.commit()
        print(
            f"Done. {'Would reject' if args.dry_run else 'Rejected'} {len(targets)} demo bet(s)."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
