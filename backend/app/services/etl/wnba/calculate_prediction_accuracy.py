"""Write per-prop actuals from yesterday's box scores for accuracy tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAAssistsActuals,
    WNBAPointsActuals,
    WNBARecentGames,
    WNBAReboundsActuals,
)
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)


def run() -> dict:
    yesterday = now_eastern().date() - timedelta(days=1)
    db = SessionLocal()
    actuals_written = 0
    try:
        rows = (
            db.query(WNBARecentGames)
            .filter(WNBARecentGames.game_date == yesterday)
            .all()
        )
        now = datetime.utcnow()
        for r in rows:
            if r.points is not None:
                db.merge(WNBAPointsActuals(
                    date=yesterday, player_id=r.player_id,
                    player_name=None, actual_points=float(r.points),
                    created_at=now,
                ))
                actuals_written += 1
            if r.assists is not None:
                db.merge(WNBAAssistsActuals(
                    date=yesterday, player_id=r.player_id,
                    player_name=None, actual_assists=float(r.assists),
                    created_at=now,
                ))
                actuals_written += 1
            if r.rebounds is not None:
                db.merge(WNBAReboundsActuals(
                    date=yesterday, player_id=r.player_id,
                    player_name=None, actual_rebounds=float(r.rebounds),
                    created_at=now,
                ))
                actuals_written += 1
        db.commit()
        return {
            "status": "ok",
            "date": yesterday.isoformat(),
            "actuals_written": actuals_written,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
