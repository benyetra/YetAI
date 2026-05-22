"""Refresh pred_wnba_team_roster from stats.wnba.com.

Mirrors app/services/etl/nba/update_team_roster.py but iterates over the
canonical WNBA team list from _team_id_map.WNBA_ID_TO_NAME.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import WNBATeamRoster
from app.services.etl.wnba import _wnba_stats
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba._team_id_map import WNBA_ID_TO_NAME

logger = logging.getLogger(__name__)


def _current_season() -> str:
    """WNBA season is the calendar year (e.g., 2026)."""
    return str(now_eastern().year)


def run(season: str | None = None) -> dict:
    season = season or _current_season()
    players_seen = 0
    teams_processed = 0
    errors = 0

    db = SessionLocal()
    upsert_rows: list[dict] = []
    try:
        for wnba_team_id, team_name in WNBA_ID_TO_NAME.items():
            try:
                rows = _wnba_stats.fetch_team_roster(team_id=int(wnba_team_id), season=season)
            except Exception as exc:
                logger.warning("roster fetch failed for %s: %s", team_name, exc)
                errors += 1
                continue

            teams_processed += 1
            for row in rows:
                player_id = row.get("PLAYER_ID")
                player_name = row.get("PLAYER")
                if not player_id or not player_name:
                    continue
                upsert_rows.append(
                    {
                        "team_id": int(wnba_team_id),
                        "player_id": int(player_id),
                        "player_name": player_name,
                        "last_updated": datetime.utcnow(),
                        "position": row.get("POSITION"),
                    }
                )
                players_seen += 1
        upsert_many(
            db,
            WNBATeamRoster,
            upsert_rows,
            conflict_keys=["team_id", "player_id"],
        )
        db.commit()
        return {
            "status": "ok",
            "season": season,
            "teams_processed": teams_processed,
            "players_seen": players_seen,
            "errors": errors,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
