"""
Start/sit recommendation helpers.

Resolves the user's Sleeper team via connected ``platform_user_id`` ↔ roster
``owner_id`` instead of username heuristics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def find_user_team_in_standings(
    standings: List[Dict[str, Any]], platform_user_id: str
) -> Optional[Dict[str, Any]]:
    """Return the standings row owned by the connected Sleeper user."""
    if not platform_user_id or not standings:
        return None

    owner_id = str(platform_user_id)
    for team in standings:
        if str(team.get("owner_id", "")) == owner_id:
            return team
    return None


def filter_leagues_for_start_sit(
    leagues: List[Dict[str, Any]], league_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return all leagues or a single league when ``league_id`` is provided."""
    if not league_id:
        return leagues

    target = str(league_id)
    filtered = [
        league
        for league in leagues
        if str(league.get("league_id") or league.get("id")) == target
    ]
    return filtered


def resolve_platform_user_id(league: Dict[str, Any]) -> Optional[str]:
    """Sleeper user id for the connected account that owns this league row."""
    platform_user_id = league.get("platform_user_id")
    if platform_user_id:
        return str(platform_user_id)
    return None
