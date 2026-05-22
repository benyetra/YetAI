"""Refresh pred_wnba_team_roster from stats.wnba.com.

Prefer one LeagueDashPlayerStats call (fast). Fall back to per-team
CommonTeamRoster only when the league dashboard is empty or unavailable.
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


def _rows_from_league_player_stats(season: str) -> list[dict] | None:
    """Single league-wide fetch; None if the API call failed."""
    try:
        stats_rows = _wnba_stats.fetch_league_player_stats(season=season)
    except Exception as exc:
        logger.warning("league player stats roster fetch failed: %s", exc)
        return None

    upsert_rows: list[dict] = []
    for row in stats_rows:
        team_id = row.get("TEAM_ID")
        player_id = row.get("PLAYER_ID")
        player_name = row.get("PLAYER_NAME")
        if team_id is None or player_id is None or not player_name:
            continue
        tid = int(team_id)
        if tid not in WNBA_ID_TO_NAME:
            continue
        upsert_rows.append(
            {
                "team_id": tid,
                "player_id": int(player_id),
                "player_name": player_name,
                "last_updated": datetime.utcnow(),
                "position": None,
            }
        )
    return upsert_rows


def _rows_from_per_team_rosters(season: str) -> tuple[list[dict], int, int]:
    """Legacy path: one CommonTeamRoster call per team (slow; rate-limit prone)."""
    upsert_rows: list[dict] = []
    teams_processed = 0
    errors = 0

    for wnba_team_id, team_name in WNBA_ID_TO_NAME.items():
        try:
            rows = _wnba_stats.fetch_team_roster(
                team_id=int(wnba_team_id), season=season
            )
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

    return upsert_rows, teams_processed, errors


def run(season: str | None = None) -> dict:
    season = season or _current_season()
    upsert_rows = _rows_from_league_player_stats(season)
    source = "league_dash_player_stats"
    teams_processed = 0
    errors = 0

    if not upsert_rows:
        logger.info(
            "league player stats empty or failed — falling back to per-team roster (%d teams)",
            len(WNBA_ID_TO_NAME),
        )
        upsert_rows, teams_processed, errors = _rows_from_per_team_rosters(season)
        source = "common_team_roster"

    players_seen = len(upsert_rows)

    db = SessionLocal()
    try:
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
            "source": source,
            "teams_processed": teams_processed,
            "players_seen": players_seen,
            "errors": errors,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
