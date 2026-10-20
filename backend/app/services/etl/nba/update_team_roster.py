"""Refresh pred_team_roster from API-Sports NBA v2 (Development-1nt sub Dev-0ai).

Stores NBA.com player ids in pred_team_roster so downstream tables
(RecentGames, YesterdaysPlayers, projections) join cleanly. API-Sports team
ids and NBA.com ids are mapped via API_SPORTS_TO_NBA in `_api_sports.py`.

ESPN's live team rosters settle which team a player is on: API-Sports can lag
on trades and list a moved player under both teams. Players ESPN lists that
API-Sports doesn't yet are added when they resolve to a real NBA.com id.

The table is replaced in one transaction, and only when the new roster looks
complete — a thin API-Sports response at season rollover must not wipe it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import TeamRoster
from app.services.etl.nba._api_sports import (
    API_SPORTS_TO_NBA,
    SYNTHETIC_ID_BASE,
    api_request,
    expand_player_name,
    get_current_season,
    normalize_player_name,
    resolve_nba_player_id,
)
from app.services.etl.nba._espn import fetch_team_rosters, now_eastern

logger = logging.getLogger(__name__)

# A full league is ~30 teams × 15–18 players; anything far below means the
# upstream response was partial and the existing roster should be kept.
MIN_ROSTER_PLAYERS = 300
MIN_ROSTER_TEAMS = 25
# ESPN coverage needed before it may override API-Sports team assignments.
MIN_ESPN_TEAMS = 25


@dataclass
class RosterEntry:
    player_id: int
    player_name: str
    team_id: int
    position: str


def merge_rosters(
    api_players: list[tuple[int, str, int | None, str]],
    espn_rosters: dict[int, list[str]],
) -> tuple[list[RosterEntry], dict]:
    """Combine API-Sports players with ESPN's current team assignments.

    api_players: (nba_team_id, player_name, api_sports_player_id, position)
    espn_rosters: nba_team_id -> names (empty/partial when ESPN is down)

    Returns (entries, stats). Pure function — unit-tested without a DB.
    """
    use_espn = len(espn_rosters) >= MIN_ESPN_TEAMS
    espn_team_by_name: dict[str, int] = {}
    league_names: list[str] = []
    if use_espn:
        for team_id, names in espn_rosters.items():
            league_names.extend(names)
            for name in names:
                espn_team_by_name[normalize_player_name(name)] = team_id

    stats = {
        "espn_used": use_espn,
        "espn_team_overrides": 0,
        "espn_only_added": 0,
        "synthetic_ids": 0,
        "players_unmatched": 0,
    }
    entries: dict[int, RosterEntry] = {}
    seen_names: set[str] = set()

    for team_id, name, api_id, position in api_players:
        # API-Sports abbreviates some names ("C. Flagg") or swaps them
        # ("Demin Egor"); take ESPN's full name from the same team.
        if use_espn:
            name = expand_player_name(name, espn_rosters.get(team_id, []), league_names)
        key = normalize_player_name(name)
        player_id = resolve_nba_player_id(name, api_sports_id=api_id)
        if not player_id:
            stats["players_unmatched"] += 1
            continue
        espn_team = espn_team_by_name.get(key)
        if player_id in entries:
            # Listed under two teams (traded) — ESPN decides, else first wins.
            if espn_team and entries[player_id].team_id != espn_team:
                entries[player_id].team_id = espn_team
            continue
        if espn_team and espn_team != team_id:
            stats["espn_team_overrides"] += 1
            team_id = espn_team
        seen_names.add(key)
        entries[player_id] = RosterEntry(player_id, name, team_id, position)

    if use_espn:
        for team_id, names in espn_rosters.items():
            for name in names:
                key = normalize_player_name(name)
                if key in seen_names:
                    continue
                # No API-Sports id here, so only add players with a real
                # NBA.com id — a synthetic id would not match their box scores.
                player_id = resolve_nba_player_id(name)
                if not player_id or player_id in entries:
                    continue
                seen_names.add(key)
                entries[player_id] = RosterEntry(player_id, name, team_id, "Unknown")
                stats["espn_only_added"] += 1

    stats["synthetic_ids"] = sum(
        1 for e in entries.values() if e.player_id >= SYNTHETIC_ID_BASE
    )
    return list(entries.values()), stats


def _fetch_api_sports_players(season: int) -> tuple[list[tuple], int, int]:
    """Returns (players, teams_processed, teams_no_match)."""
    teams_data = api_request("teams", params={"league": "standard"})
    if not teams_data or not teams_data.get("response"):
        return [], 0, 0

    teams = teams_data["response"]
    logger.info("update_team_roster: api-sports returned %d teams", len(teams))
    players: list[tuple] = []
    teams_processed = 0
    teams_no_match = 0
    for team in teams:
        nba_team_id = API_SPORTS_TO_NBA.get(team["id"])
        if not nba_team_id:
            teams_no_match += 1
            continue
        players_data = api_request(
            "players", params={"team": team["id"], "season": season}
        )
        if not players_data or not players_data.get("response"):
            logger.info("update_team_roster: no players for %s", team.get("name"))
            continue
        for player in players_data["response"]:
            firstname = (player.get("firstname") or "").strip()
            lastname = (player.get("lastname") or "").strip()
            name = f"{firstname} {lastname}".strip()
            if not name:
                continue
            position = (player.get("leagues") or {}).get("standard", {}).get(
                "pos"
            ) or "Unknown"
            players.append((nba_team_id, name, player.get("id"), position))
        teams_processed += 1
        time.sleep(0.2)
    return players, teams_processed, teams_no_match


def run() -> dict:
    """Refresh pred_team_roster end-to-end. Returns a summary dict."""
    season = get_current_season()
    api_players, teams_processed, teams_no_match = _fetch_api_sports_players(season)
    if not api_players:
        return {"status": "error", "reason": "failed_to_fetch_players"}

    espn_rosters = fetch_team_rosters()
    entries, merge_stats = merge_rosters(api_players, espn_rosters)
    teams_with_players = len({e.team_id for e in entries})

    summary = {
        "season": season,
        "teams_processed": teams_processed,
        "teams_no_match": teams_no_match,
        "espn_teams": len(espn_rosters),
        "total_players": len(entries),
        "teams_with_players": teams_with_players,
        **merge_stats,
    }
    if len(entries) < MIN_ROSTER_PLAYERS or teams_with_players < MIN_ROSTER_TEAMS:
        logger.error(
            "update_team_roster: only %d players on %d teams — keeping existing roster",
            len(entries),
            teams_with_players,
        )
        return {"status": "error", "reason": "incomplete_roster", **summary}

    db = SessionLocal()
    try:
        updated_at = datetime.now(now_eastern().tzinfo)
        db.query(TeamRoster).delete(synchronize_session=False)
        db.add_all(
            TeamRoster(
                player_id=e.player_id,
                player_name=e.player_name,
                team_id=e.team_id,
                position=e.position,
                last_updated=updated_at,
            )
            for e in entries
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info("update_team_roster: %s", summary)
    return {"status": "ok", **summary}
