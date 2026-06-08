"""Trade value helper for trade analyzer routes."""

from typing import Any, Dict, Optional

from app.services.fantasy_draft_picks import format_roster_tradeable_picks
from app.services.fantasy_sleeper_trade_proposal import (
    calculate_realistic_trade_value as _calculate_realistic_trade_value,
    load_league_pick_context as _load_league_pick_context,
)

# Re-export for tests and callers
format_roster_traded_picks = format_roster_tradeable_picks


def calculate_realistic_trade_value(
    player: Dict[str, Any],
    *,
    scoring_type: str = "ppr",
    league_format: Optional[Dict[str, Any]] = None,
) -> float:
    """Calculate stable player trade value based on Sleeper metadata."""
    return _calculate_realistic_trade_value(
        player,
        scoring_type=scoring_type,
        league_format=league_format,
    )


async def load_league_pick_context(
    sleeper_service: Any, league_id: str
) -> Dict[str, Any]:
    """Fetch league metadata, traded picks, and pick registry for trade routes."""
    return await _load_league_pick_context(sleeper_service, league_id)
