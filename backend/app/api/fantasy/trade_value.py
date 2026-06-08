"""Trade value helper for trade analyzer routes."""

from typing import Any, Dict, List

from app.services.fantasy_draft_picks import (
    build_league_pick_registry,
    calculate_draft_pick_trade_value,
    calculate_faab_trade_value,
    format_roster_tradeable_picks,
    lookup_pick_trade_value,
)
from app.services.fantasy_trade_value import calculate_deterministic_trade_value

# Re-export for tests and callers
format_roster_traded_picks = format_roster_tradeable_picks


def calculate_realistic_trade_value(
    player: Dict[str, Any], *, scoring_type: str = "ppr"
) -> float:
    """Calculate stable player trade value based on Sleeper metadata."""
    return calculate_deterministic_trade_value(player, scoring_type=scoring_type)


async def load_league_pick_context(
    sleeper_service: Any, league_id: str
) -> Dict[str, Any]:
    """Fetch league metadata, traded picks, and pick registry for trade routes."""
    league = await sleeper_service.get_league(league_id)
    traded_picks = await sleeper_service.get_league_traded_picks(league_id)
    registry = build_league_pick_registry(league, traded_picks)
    return {
        "league": league,
        "traded_picks": traded_picks,
        "pick_registry": registry,
        "is_dynasty": int((league.get("settings") or {}).get("type", 0)) == 2,
    }
