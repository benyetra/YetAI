"""Trade value helper for trade analyzer routes."""

from typing import Any, Dict

from app.services.fantasy_trade_value import calculate_deterministic_trade_value


def calculate_realistic_trade_value(player: Dict[str, Any]) -> float:
    """Calculate stable player trade value based on Sleeper metadata."""
    return calculate_deterministic_trade_value(player)
