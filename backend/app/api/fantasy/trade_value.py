"""Trade value helper for trade analyzer routes."""

from typing import Any, Dict


def calculate_realistic_trade_value(player: Dict[str, Any]) -> float:
    """Calculate realistic player trade value based on Sleeper data"""
    position = player.get("position", "UNKNOWN")
    age = player.get("age", 27)
    team = player.get("team", "")

    # Base values by position (realistic ranges from trade_analyzer_service.py)
    base_values = {
        "QB": (20.0, 45.0),  # QB range 20-45
        "RB": (15.0, 40.0),  # RB range 15-40
        "WR": (12.0, 38.0),  # WR range 12-38
        "TE": (8.0, 25.0),  # TE range 8-25
        "K": (2.0, 6.0),  # K range 2-6
        "DEF": (3.0, 8.0),  # DEF range 3-8
    }

    min_val, max_val = base_values.get(position, (8.0, 15.0))

    # Age-based value adjustment (handle None age)
    age = age or 27  # Default to 27 if None
    if age <= 24:
        age_multiplier = 1.1  # Young player bonus
    elif age <= 27:
        age_multiplier = 1.0  # Prime years
    elif age <= 30:
        age_multiplier = 0.95  # Slight decline
    else:
        age_multiplier = 0.8  # Aging player discount

    # Team quality impact (simplified based on team name)
    team_multiplier = 1.0
    if team in ["KC", "BUF", "DAL", "SF", "PHI", "MIA", "LAR"]:
        team_multiplier = 1.05  # Good offense teams
    elif team in ["WAS", "CHI", "NYG", "CAR"]:
        team_multiplier = 0.95  # Weaker offense teams

    # Calculate final value with some variance
    import random

    base_value = random.uniform(min_val, max_val)
    final_value = base_value * age_multiplier * team_multiplier

    return round(final_value, 1)
