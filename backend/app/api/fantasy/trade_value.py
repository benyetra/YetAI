"""Trade value helper for trade analyzer routes."""

from datetime import datetime
from typing import Any, Dict, List


from app.services.fantasy_trade_value import calculate_deterministic_trade_value


def calculate_realistic_trade_value(player: Dict[str, Any]) -> float:
    """Calculate stable player trade value based on Sleeper metadata."""
    return calculate_deterministic_trade_value(player)


def calculate_draft_pick_trade_value(season: int, round_number: int) -> float:
    """Dynasty-style draft pick values by round (matches trade analyzer UI scale)."""
    base_values = {1: 35.0, 2: 18.0, 3: 8.0, 4: 4.0}
    base_value = base_values.get(round_number, 2.0)
    years_out = season - datetime.now().year
    if years_out > 0:
        base_value *= 0.9**years_out
    elif years_out < 0:
        base_value *= 0.5
    return round(base_value, 1)


def format_roster_traded_picks(
    traded_picks: List[Dict[str, Any]], roster_id: int
) -> List[Dict[str, Any]]:
    """Map Sleeper traded_picks rows owned by roster_id to trade-analyzer shape."""
    formatted: List[Dict[str, Any]] = []
    for pick in traded_picks:
        owner = pick.get("owner_id") or pick.get("roster_id")
        if owner is None or int(owner) != int(roster_id):
            continue
        season = int(pick.get("season") or datetime.now().year)
        round_num = int(pick.get("round") or 1)
        pick_key = f"{season}-{round_num}-{roster_id}"
        pick_id = abs(hash(pick_key)) % 2147483647
        formatted.append(
            {
                "pick_id": pick_id,
                "season": season,
                "round": round_num,
                "description": f"{season} Round {round_num} Pick",
                "trade_value": calculate_draft_pick_trade_value(season, round_num),
                "roster_id": int(roster_id),
                "previous_owner_id": pick.get("previous_owner_id"),
            }
        )
    formatted.sort(key=lambda p: (p["season"], p["round"]))
    return formatted
