"""Refresh pred_wnba_player_injury_status from the ESPN WNBA injuries feed.

Player ID resolution: look up player_name against pred_wnba_team_roster
(case-insensitive). Players not found are logged and skipped.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.predictions_models import WNBAPlayerInjuryStatus, WNBATeamRoster
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import fetch_injuries

logger = logging.getLogger(__name__)

# Map ESPN status strings to our compact status values.
ESPN_STATUS_MAP = {
    "Out": "out",
    "Questionable": "questionable",
    "Doubtful": "doubtful",
    "Day-To-Day": "questionable",
    "Probable": "healthy",
    "Injured Reserve": "ir",
}


def _normalize_status(espn_status: str) -> str:
    return ESPN_STATUS_MAP.get(espn_status, "out")


def run() -> dict:
    rows = fetch_injuries()
    db = SessionLocal()
    matched = 0
    unmatched = 0
    upsert_rows: list[dict] = []
    try:
        for row in rows:
            name = (row.get("player_name") or "").strip()
            if not name:
                continue

            roster_row = (
                db.query(WNBATeamRoster)
                .filter(func.lower(WNBATeamRoster.player_name) == name.lower())
                .first()
            )
            if not roster_row:
                logger.info("injury: skipping unmatched player %s", name)
                unmatched += 1
                continue

            upsert_rows.append(
                {
                    "player_id": roster_row.player_id,
                    "player_name": name,
                    "status": _normalize_status(row.get("status") or "Out"),
                    "injury_type": row.get("injury_type"),
                    "date_updated": datetime.utcnow(),
                }
            )
            matched += 1
        upsert_many(
            db,
            WNBAPlayerInjuryStatus,
            upsert_rows,
            conflict_keys=["player_id"],
        )
        db.commit()
        return {
            "status": "ok",
            "matched": matched,
            "unmatched": unmatched,
            "total_rows": len(rows),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
