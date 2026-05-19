"""Refresh pred_team_roster from API-Sports NBA v2 (Development-1nt sub Dev-0ai).

Port of YetiBets/scripts/nba/update_team_roster_api_sports.py. The unusual bit:
we store **NBA.com player ids**, not API-Sports player ids, because the rest of
the prediction schema (RecentGames, YesterdaysPlayers, projections) keys on
NBA.com ids. nba_api's static player list is the canonical source for that
lookup; we keep a small manual override for players the static list misses
(e.g., recent draftees).

Requires `NBA_API_KEY` env var on the worker.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Optional

import requests
from nba_api.stats.static import players as nba_players  # type: ignore

from app.core.database import SessionLocal
from app.models.predictions_models import TeamRoster
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)

API_BASE_URL = "https://v2.nba.api-sports.io"
API_KEY_ENV = "NBA_API_KEY"

# API-Sports team_id → NBA.com team_id. Embedded from YetiBets
# scripts/nba/team_id_mapping.json (30 NBA teams; ids 31 and 37 both map to
# the Spurs in source data — preserved as-is for parity).
API_SPORTS_TO_NBA: dict[int, int] = {
    1: 1610612737, 2: 1610612738, 4: 1610612751, 5: 1610612766,
    6: 1610612741, 7: 1610612739, 8: 1610612742, 9: 1610612743,
    10: 1610612765, 11: 1610612744, 14: 1610612745, 15: 1610612754,
    16: 1610612746, 17: 1610612747, 19: 1610612763, 20: 1610612748,
    21: 1610612749, 22: 1610612750, 23: 1610612740, 24: 1610612752,
    25: 1610612760, 26: 1610612753, 27: 1610612755, 28: 1610612756,
    29: 1610612757, 30: 1610612758, 31: 1610612759, 37: 1610612759,
    38: 1610612761, 40: 1610612762, 41: 1610612764,
}

# Players missing from nba_api's static list — usually recent draftees.
# Lowercase keys; values are NBA.com player ids. Sourced from the YetiBets
# script's MANUAL_PLAYER_IDS table.
MANUAL_PLAYER_IDS: dict[str, int] = {
    "nikola jokic": 203999,
    "victor wembanyama": 1641705,
    "chet holmgren": 1631096,
    "scoot henderson": 1641706,
    "jaime jaquez jr": 1641707,
    "amen thompson": 1641708,
    "ausar thompson": 1641709,
    "brandon miller": 1641710,
    "gradey dick": 1641711,
    "cam whitmore": 1631170,
    "keyonte george": 1641712,
    "bilal coulibaly": 1641713,
    "dereck lively ii": 1641714,
    "jordan hawkins": 1641715,
    "jett howard": 1641716,
    "taylor hendricks": 1641717,
    "kobe bufkin": 1641718,
}


def _api_request(endpoint: str, params: dict | None = None) -> dict | None:
    """GET against API-Sports v2.nba with naive retry on 429 / network errors."""
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} env var is required for update_team_roster")
    url = f"{API_BASE_URL}/{endpoint}"
    headers = {"x-apisports-key": api_key}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                logger.warning("api-sports rate-limited, sleeping 60s")
                time.sleep(60)
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("api-sports %s failed (attempt %d/3): %s", endpoint, attempt + 1, exc)
            if attempt < 2:
                time.sleep(5)
    return None


def _resolve_nba_player_id(player_name: str, static_players: list[dict]) -> Optional[int]:
    search = player_name.lower().strip()
    if search in MANUAL_PLAYER_IDS:
        return MANUAL_PLAYER_IDS[search]
    for p in static_players:
        if p["full_name"].lower() == search:
            return p["id"]
    for p in static_players:
        full = p["full_name"].lower()
        if search in full or full in search:
            return p["id"]
    return None


def run() -> dict:
    """Refresh pred_team_roster end-to-end.

    Returns a summary dict: total_players inserted, teams_processed,
    teams_no_match (api team id wasn't in API_SPORTS_TO_NBA), players_unmatched
    (couldn't resolve to an NBA.com id and were skipped).
    """
    teams_data = _api_request("teams", params={"league": "standard"})
    if not teams_data or not teams_data.get("response"):
        return {"status": "error", "reason": "failed_to_fetch_teams"}

    static_players = nba_players.get_players()
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
        # Full-refresh semantics match the original script (DELETE before reinsert).
        db.query(TeamRoster).delete(synchronize_session=False)

        seen_player_ids: set[int] = set()

        for team in teams:
            api_team_id = team["id"]
            nba_team_id = API_SPORTS_TO_NBA.get(api_team_id)
            if not nba_team_id:
                teams_no_match += 1
                continue

            team_name = team.get("name", "Unknown")
            players_data = _api_request(
                "players", params={"team": api_team_id, "season": season}
            )
            if not players_data or not players_data.get("response"):
                logger.info("update_team_roster: no players for %s (api_team=%s)", team_name, api_team_id)
                continue

            team_inserts = 0
            for player in players_data["response"]:
                firstname = (player.get("firstname") or "").strip()
                lastname = (player.get("lastname") or "").strip()
                player_name = f"{firstname} {lastname}".strip()
                if not player_name:
                    continue

                nba_player_id = _resolve_nba_player_id(player_name, static_players)
                if not nba_player_id:
                    players_unmatched += 1
                    continue
                if nba_player_id in seen_player_ids:
                    continue
                seen_player_ids.add(nba_player_id)

                position = (
                    (player.get("leagues") or {}).get("standard", {}).get("pos") or "Unknown"
                )
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
            logger.info("update_team_roster: %s — inserted %d players", team_name, team_inserts)
            teams_processed += 1
            time.sleep(0.2)  # api-sports rate-limit cushion

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
