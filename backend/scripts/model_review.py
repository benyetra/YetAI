"""Print the daily model review (what the 09:45 ET email and the admin API show).

    PYTHONPATH=. python3 scripts/model_review.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from datetime import datetime

from app.core.database import SessionLocal
from app.services.auto_pick.candidate import utc_to_eastern
from app.services.model_review_service import build_review, render_text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today ET)")
    args = ap.parse_args()
    today = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else utc_to_eastern(datetime.utcnow()).date()
    )
    db = SessionLocal()
    try:
        print(render_text(build_review(db, today)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
