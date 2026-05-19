"""Refresh pred_team_roster from API-Sports NBA v2 (Development-1nt sub Dev-0ai).

Stores NBA.com player ids in pred_team_roster so downstream tables
(RecentGames, YesterdaysPlayers, projections) join cleanly. API-Sports team
ids and NBA.com ids are mapped via API_SPORTS_TO_NBA in `_api_sports.py`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import TeamRoster
from app.services.etl.nba._api_sports import (
    API_SPORTS_TO_NBA,
    api_request,
    resolve_nba_player_id,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)


def run() -> dict:
    """Refresh pred_team_roster end-to-end. Returns a summary dict."""
    teams_data = api_request("teams", params={"league": "standard"})
    if not teams_data or not teams_data.get("response"):
        return {"status": "error", "reason": "failed_to_fetch_teams"}

    teams = teams_data["response"]
    logger.info("update_team_roster: api-sports returned %d teams", len(teams))

    # Season: NBA league year starts in October.
    now = now_eastern()
    season = now.year if now.month >= 10 else now.year - 1

    teams_processed = 0
    teams_no_match = 0
    total_players = 0
    players_unmatched = 0

    db = SessionLocal()
    try:
        db.query(TeamRoster).delete(synchronize_session=False)

        seen_player_ids: set[int] = set()

        for team in teams:
            api_team_id = team["id"]
            nba_team_id = API_SPORTS_TO_NBA.get(api_team_id)
            if not nba_team_id:
                teams_no_match += 1
                continue

            team_name = team.get("name", "Unknown")
            players_data = api_request(
                "players", params={"team": api_team_id, "season": season}
            )
            if not players_data or not players_data.get("response"):
                logger.info("update_team_roster: no players for %s", team_name)
                continue

            team_inserts = 0
            for player in players_data["response"]:
                firstname = (player.get("firstname") or "").strip()
                lastname = (player.get("lastname") or "").strip()
                player_name = f"{firstname} {lastname}".strip()
                if not player_name:
                    continue

                nba_player_id = resolve_nba_player_id(player_name)
                if not nba_player_id:
                    players_unmatched += 1
                    continue
                if nba_player_id in seen_player_ids:
                    continue
                seen_player_ids.add(nba_player_id)

                position = (player.get("leagues") or {}).get("standard", {}).get(
                    "pos"
                ) or "Unknown"
                db.add(
                    TeamRoster(
                        player_id=nba_player_id,
                        player_name=player_name,
                        team_id=nba_team_id,
                        position=position,
                        last_updated=datetime.now(now_eastern().tzinfo),
                    )
                )
                team_inserts += 1
                total_players += 1

            db.commit()
            logger.info(
                "update_team_roster: %s — inserted %d players", team_name, team_inserts
            )
            teams_processed += 1
            time.sleep(0.2)

        return {
            "status": "ok",
            "season": season,
            "teams_processed": teams_processed,
            "teams_no_match": teams_no_match,
            "total_players": total_players,
            "players_unmatched": players_unmatched,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
