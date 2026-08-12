"""Write per-prop actuals from yesterday's box scores for accuracy tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAAssistsActuals,
    WNBAPointsActuals,
    WNBAPRAActuals,
    WNBARecentGames,
    WNBAReboundsActuals,
    WNBAThreePtMadeActuals,
)
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)


def run() -> dict:
    yesterday = now_eastern().date() - timedelta(days=1)
    db = SessionLocal()
    points_rows: list[dict] = []
    assists_rows: list[dict] = []
    rebounds_rows: list[dict] = []
    threes_rows: list[dict] = []
    pra_rows: list[dict] = []
    try:
        rows = (
            db.query(WNBARecentGames)
            .filter(WNBARecentGames.game_date == yesterday)
            .all()
        )
        now = datetime.utcnow()
        for r in rows:
            if r.points is not None:
                points_rows.append(
                    {
                        "date": yesterday,
                        "player_id": r.player_id,
                        "player_name": None,
                        "actual_points": float(r.points),
                        "created_at": now,
                    }
                )
            if r.assists is not None:
                assists_rows.append(
                    {
                        "date": yesterday,
                        "player_id": r.player_id,
                        "player_name": None,
                        "actual_assists": float(r.assists),
                        "created_at": now,
                    }
                )
            if r.rebounds is not None:
                rebounds_rows.append(
                    {
                        "date": yesterday,
                        "player_id": r.player_id,
                        "player_name": None,
                        "actual_rebounds": float(r.rebounds),
                        "created_at": now,
                    }
                )
            if r.three_pt_made is not None:
                threes_rows.append(
                    {
                        "date": yesterday,
                        "player_id": r.player_id,
                        "player_name": None,
                        "actual_three_pt_made": float(r.three_pt_made),
                        "created_at": now,
                    }
                )
            if None not in (r.points, r.rebounds, r.assists):
                pra_rows.append(
                    {
                        "date": yesterday,
                        "player_id": r.player_id,
                        "player_name": None,
                        "actual_pra": float(r.points)
                        + float(r.rebounds)
                        + float(r.assists),
                        "created_at": now,
                    }
                )
        upsert_many(
            db, WNBAPointsActuals, points_rows, conflict_keys=["player_id", "date"]
        )
        upsert_many(
            db, WNBAAssistsActuals, assists_rows, conflict_keys=["player_id", "date"]
        )
        upsert_many(
            db, WNBAReboundsActuals, rebounds_rows, conflict_keys=["player_id", "date"]
        )
        upsert_many(
            db,
            WNBAThreePtMadeActuals,
            threes_rows,
            conflict_keys=["player_id", "date"],
        )
        upsert_many(db, WNBAPRAActuals, pra_rows, conflict_keys=["player_id", "date"])
        db.commit()
        return {
            "status": "ok",
            "date": yesterday.isoformat(),
            "actuals_written": (
                len(points_rows)
                + len(assists_rows)
                + len(rebounds_rows)
                + len(threes_rows)
                + len(pra_rows)
            ),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
