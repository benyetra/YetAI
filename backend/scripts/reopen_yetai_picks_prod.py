#!/usr/bin/env python3
"""
Reopen wrongly auto-settled YetAI picks on production.

Usage:
  export DATABASE_URL='postgresql://...'   # Railway Postgres
  cd backend
  PYTHONPATH=. .venv/bin/python scripts/reopen_yetai_picks_prod.py --dry-run
  PYTHONPATH=. .venv/bin/python scripts/reopen_yetai_picks_prod.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from _bootstrap_env import bootstrap_env, ensure_database_url  # noqa: E402
from _db_script_guard import assert_not_local_default_db  # noqa: E402

bootstrap_env()
ensure_database_url()

from app.core.database import SessionLocal  # noqa: E402
from app.models.database_models import YetAIBet  # noqa: E402
from app.services.yetai_bets_service_db import clamp_yetai_result  # noqa: E402

# June 9 auto-pick batch — prematurely settled 2026-06-10 during bad regrade run.
REOPEN_PICK_IDS = (
    "e62a8da2-efa8-4460-bf10-ae0e277e83f9",  # Keldon Johnson OVER 6.5 points
    "06d82efa-d649-4b4b-9096-9cabd4a53e0c",  # Luke Kornet OVER 1.5 points
)

# Stale manual parlay still showing on subscriber live board.
EXPIRE_PICK_IDS = (
    "b82b11f3-5bcb-47ea-b4b4-fb56b038bf8a",  # WNBA Freaky Friday (June 5)
)

REOPENABLE = frozenset({"won", "lost", "pushed", "expired"})
EXPIRABLE = frozenset({"pending", "active", "pending_approval"})


def _clear_parlay_leg_results(legs):
    if not isinstance(legs, list):
        return legs
    return [
        (
            {k: v for k, v in leg.items() if k != "leg_result"}
            if isinstance(leg, dict)
            else leg
        )
        for leg in legs
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print actions without committing"
    )
    args = parser.parse_args()

    assert_not_local_default_db()
    db = SessionLocal()
    try:
        for pick_id in REOPEN_PICK_IDS:
            bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
            if not bet:
                print(f"SKIP reopen {pick_id}: not found")
                continue
            if bet.status not in REOPENABLE:
                print(
                    f"SKIP reopen {pick_id}: status={bet.status!r} "
                    f"pick={bet.selection!r}"
                )
                continue
            print(f"REOPEN {pick_id}: {bet.selection!r} " f"({bet.status} -> active)")
            if not args.dry_run:
                bet.status = "active"
                bet.settled_at = None
                bet.result = None
                if bet.parlay_legs:
                    bet.parlay_legs = _clear_parlay_leg_results(bet.parlay_legs)

        for pick_id in EXPIRE_PICK_IDS:
            bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
            if not bet:
                print(f"SKIP expire {pick_id}: not found")
                continue
            if bet.status not in EXPIRABLE:
                print(
                    f"SKIP expire {pick_id}: status={bet.status!r} "
                    f"title={bet.title!r}"
                )
                continue
            print(f"EXPIRE {pick_id}: {bet.title!r} ({bet.status} -> expired)")
            if not args.dry_run:
                bet.status = "expired"
                bet.settled_at = datetime.utcnow()
                bet.result = clamp_yetai_result("Admin expired (stale pick)")

        if args.dry_run:
            print("Dry run — no changes committed.")
            db.rollback()
        else:
            db.commit()
            print("Committed.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
