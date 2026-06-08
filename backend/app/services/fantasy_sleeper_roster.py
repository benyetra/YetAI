"""Fetch Sleeper league rosters for trade analyzer endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from app.services.fantasy_trade_value import calculate_deterministic_trade_value

logger = logging.getLogger(__name__)


def _numeric_player_id(player_id: str) -> int:
    if player_id.isdigit():
        return int(player_id)
    return hash(player_id) % 2147483647


def format_sleeper_player_row(
    player_id: str,
    player: Dict[str, Any],
    *,
    scoring_type: str = "ppr",
    league_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize a Sleeper player dict for trade analyzer responses."""
    trade_value = calculate_deterministic_trade_value(
        player,
        scoring_type=scoring_type,
        league_format=league_format,
    )
    return {
        "id": _numeric_player_id(player_id),
        "player_id": player_id,
        "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
        "position": player.get("position", "UNKNOWN"),
        "team": player.get("team", "UNKNOWN"),
        "age": player.get("age", 0),
        "trade_value": trade_value,
    }


async def fetch_league_rosters(league_id: str) -> List[Dict[str, Any]]:
    """Return raw Sleeper roster documents for a league."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(
                    "Failed to fetch rosters for league %s: %s",
                    league_id,
                    response.status,
                )
                return []
            data = await response.json()
            return data if isinstance(data, list) else []


def find_roster_for_team(
    rosters: List[Dict[str, Any]], team_id: int
) -> Optional[Dict[str, Any]]:
    """Match a Sleeper roster by roster_id."""
    team_key = str(team_id)
    for roster in rosters:
        roster_id = roster.get("roster_id")
        if roster_id == team_id or str(roster_id) == team_key:
            return roster
    return None


async def fetch_team_roster_players(
    sleeper_service: Any,
    league_id: str,
    team_id: int,
    *,
    scoring_type: str = "ppr",
    league_format: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Load normalized player rows for one Sleeper roster."""
    rosters = await fetch_league_rosters(league_id)
    target_roster = find_roster_for_team(rosters, team_id)
    if not target_roster or not target_roster.get("players"):
        return []

    all_players = await sleeper_service._get_all_players()
    roster_data: List[Dict[str, Any]] = []
    for player_id in target_roster["players"]:
        player = all_players.get(player_id)
        if player:
            roster_data.append(
                format_sleeper_player_row(
                    player_id,
                    player,
                    scoring_type=scoring_type,
                    league_format=league_format,
                )
            )
    return roster_data


async def fetch_team_players_by_position(
    sleeper_service: Any,
    league_id: str,
    team_id: int,
    position: str,
    *,
    limit: int = 1,
    scoring_type: str = "ppr",
    league_format: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return the highest-value real players at a position on a roster."""
    roster = await fetch_team_roster_players(
        sleeper_service,
        league_id,
        team_id,
        scoring_type=scoring_type,
        league_format=league_format,
    )
    matches = [p for p in roster if p.get("position") == position]
    if not matches:
        return []
    matches.sort(key=lambda p: p.get("trade_value") or 0, reverse=True)
    return matches[:limit]
