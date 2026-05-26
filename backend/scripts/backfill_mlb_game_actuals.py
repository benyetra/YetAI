#!/usr/bin/env python3
"""Re-grade MLB game actuals for dates that already have projections.

Updates pred_game_actuals.ml_correct / spread_correct / total_correct using
the shared mlb_game_picks grading logic (and stores spread_recommendation on
projections when missing).

Usage (production URL via Railway resolver):
  cd backend
  export RAILWAY_TOKEN=...
  export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
  PYTHONPATH=. python3 scripts/backfill_mlb_game_actuals.py --days 45

Dry run:
  PYTHONPATH=. python3 scripts/backfill_mlb_game_actuals.py --days 7 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=45,
        help="Reprocess projection dates within this many days (default 45)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List dates only; do not write actuals",
    )
    args = parser.parse_args()

    from app.services.etl.mlb._db import close_session, init_session, db_session
    from app.models.predictions_models import GameProjections
    from app.services.etl.mlb.game_projection_pipeline import store_game_actuals
    from app.services.mlb_game_picks import derive_spread_recommendation_row

    cutoff = date.today() - timedelta(days=max(args.days, 1))

    init_session()
    try:
        dates = [
            row[0]
            for row in db_session.query(GameProjections.date)
            .filter(GameProjections.date >= cutoff, GameProjections.date < date.today())
            .distinct()
            .order_by(GameProjections.date)
            .all()
        ]
        if not dates:
            logger.warning("No projection dates found since %s", cutoff.isoformat())
            return 0

        logger.info(
            "Found %d dates with game projections (%s .. %s)",
            len(dates),
            dates[0],
            dates[-1],
        )

        if args.dry_run:
            for d in dates:
                logger.info("would backfill %s", d.isoformat())
            return 0

        total_stored = 0
        for target_date in dates:
            # Ensure spread_recommendation is persisted before grading actuals.
            rows = db_session.query(GameProjections).filter_by(date=target_date).all()
            updated_spread = 0
            for proj in rows:
                if proj.spread_recommendation:
                    continue
                spread = derive_spread_recommendation_row(
                    {"run_line": proj.run_line, "market_spread": proj.market_spread}
                )
                if spread:
                    proj.spread_recommendation = spread
                    updated_spread += 1
            if updated_spread:
                db_session.commit()
                logger.info(
                    "%s: set spread_recommendation on %d rows",
                    target_date,
                    updated_spread,
                )

            count = store_game_actuals(target_date)
            total_stored += count
            logger.info("%s: stored/updated %d game actuals", target_date, count)

        logger.info("Done. %d dates, %d actual rows touched.", len(dates), total_stored)
        return 0
    finally:
        close_session()


if __name__ == "__main__":
    sys.exit(main())
