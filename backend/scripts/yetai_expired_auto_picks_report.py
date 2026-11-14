"""
List auto YetAI picks an admin expired (status=expired, result "Admin expired...") that the
settlement sweep cannot prove were shown (no linked user copy), so the owner can decide.

Dry run (default) prints each candidate with the evidence fields. To move chosen rows to
history as void (the same thing the sweep does for proven-shown rows):

    PYTHONPATH=. python scripts/yetai_expired_auto_picks_report.py --apply --ids ID1,ID2

Idempotent: rows already void are no longer listed.
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal  # noqa: E402
from app.models.database_models import BetSource, YetAIBet  # noqa: E402
from app.services.yetai_bets_service_db import YetAIBetsServiceDB  # noqa: E402


def candidates(db) -> list:
    svc = YetAIBetsServiceDB()
    rows = (
        db.query(YetAIBet)
        .filter(
            YetAIBet.status == "expired",
            YetAIBet.result.ilike("Admin expired%"),
            YetAIBet.source != BetSource.MANUAL,
        )
        .order_by(YetAIBet.created_at)
        .all()
    )
    return [b for b in rows if not svc._admin_expired_shown(db, b)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ids", default="", help="comma-separated ids to void")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = candidates(db)
        for b in rows:
            factors = (
                b.prediction_factors if isinstance(b.prediction_factors, dict) else {}
            )
            print(
                f"{b.id} created={b.created_at} commence={b.commence_time} "
                f"settled_at={b.settled_at} sport={b.sport} pick={b.selection!r} "
                f"settle_attempts={(factors.get('settlement') or {}).get('attempts')}"
            )
        print(f"{len(rows)} candidate(s)")
        if not args.apply:
            print("Dry run. Pass --apply --ids ... to void chosen rows.")
            return
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        changed = 0
        for b in rows:
            if b.id in wanted:
                b.status = "void"  # keeps the admin's reason in `result`
                b.settled_at = b.settled_at or datetime.utcnow()
                changed += 1
        db.commit()
        print(f"Voided {changed} row(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
