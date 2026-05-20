"""Travel and Jet Lag Fatigue Module.

Models the impact of travel on team performance, focusing on eastward
jet lag across 2+ time zones — the only travel factor with robust,
PNAS-published evidence of significant effects.

Research basis:
- Allada et al. (PNAS, 46,535 games): eastward travel affects pitching (more HR allowed)
- Eastward travel can cancel home-field advantage for returning teams
- Effect worth ~0.1-0.3 runs/game in specific scenarios
- Day games after night games: <0.1 runs/game (confounded by lineup changes)
- Pure travel distance without timezone changes: no significant impact

Technical Playbook §9 — Travel Effects.
"""

import sys
import os

import logging
import statsapi as mlbstatsapi
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CURRENT_SEASON = 2026

# Team home timezone offsets from UTC (standard time)
# Used to compute timezone crossing between cities
TEAM_TIMEZONE = {
    "Arizona Diamondbacks": -7,
    "Atlanta Braves": -5,
    "Baltimore Orioles": -5,
    "Boston Red Sox": -5,
    "Chicago Cubs": -6,
    "Chicago White Sox": -6,
    "Cincinnati Reds": -5,
    "Cleveland Guardians": -5,
    "Colorado Rockies": -7,
    "Detroit Tigers": -5,
    "Houston Astros": -6,
    "Kansas City Royals": -6,
    "Los Angeles Angels": -8,
    "Los Angeles Dodgers": -8,
    "Miami Marlins": -5,
    "Milwaukee Brewers": -6,
    "Minnesota Twins": -6,
    "New York Mets": -5,
    "New York Yankees": -5,
    "Oakland Athletics": -8,
    "Philadelphia Phillies": -5,
    "Pittsburgh Pirates": -5,
    "San Diego Padres": -8,
    "San Francisco Giants": -8,
    "Seattle Mariners": -8,
    "St. Louis Cardinals": -6,
    "Tampa Bay Rays": -5,
    "Texas Rangers": -6,
    "Toronto Blue Jays": -5,
    "Washington Nationals": -5,
    "Athletics": -8,  # Alias for 2025-2027 Sacramento era
}

# Eastward jet lag run adjustment per timezone crossed (2+ zones)
EASTWARD_JET_LAG_PER_ZONE = 0.10  # runs/game per timezone crossed

# Maximum jet lag adjustment cap
MAX_JET_LAG_ADJUSTMENT = 0.30

# Day game after night game penalty
DAY_AFTER_NIGHT_PENALTY = 0.05


def get_team_recent_schedule(team_id, target_date=None):
    """Fetch a team's recent games to determine travel pattern.

    Returns list of recent game dicts with dates and locations.
    """
    if target_date is None:
        target_date = date.today()

    start = target_date - timedelta(days=5)
    start_str = start.strftime("%Y-%m-%d")
    end_str = target_date.strftime("%Y-%m-%d")

    try:
        schedule = mlbstatsapi.schedule(
            start_date=start_str, end_date=end_str, team=team_id
        )
        return schedule
    except Exception as e:
        logger.warning(f"Failed to fetch schedule for team {team_id}: {e}")
        return []


def compute_timezone_crossing(prev_team_name, current_team_name):
    """Compute timezone difference between two teams' home cities.

    Returns:
        int: timezone difference (positive = eastward travel)
    """
    prev_tz = TEAM_TIMEZONE.get(prev_team_name, -6)
    curr_tz = TEAM_TIMEZONE.get(current_team_name, -6)

    # Positive difference = traveling east (more negative UTC offset to less negative)
    return curr_tz - prev_tz


def compute_travel_fatigue(
    team_id, team_name, opponent_name, is_home=True, target_date=None
):
    """Compute travel fatigue adjustment for a team.

    Focuses on eastward jet lag across 2+ time zones — the primary
    evidence-based travel effect.

    Args:
        team_id: MLB team ID
        team_name: team's full name
        opponent_name: opponent's full name
        is_home: whether this team is at home
        target_date: game date

    Returns:
        dict with:
            travel_adjustment: float (runs added for opposing team)
            timezone_zones_crossed: int
            direction: str ('eastward', 'westward', 'none')
            is_day_after_night: bool
    """
    if target_date is None:
        target_date = date.today()

    schedule = get_team_recent_schedule(team_id, target_date)

    if not schedule:
        return {
            "travel_adjustment": 0.0,
            "timezone_zones_crossed": 0,
            "direction": "none",
            "is_day_after_night": False,
        }

    # Find the most recent completed game before target_date
    prev_game = None
    for game in sorted(schedule, key=lambda g: g.get("game_date", ""), reverse=True):
        game_date = game.get("game_date", "")[:10]
        if game_date < target_date.isoformat():
            prev_game = game
            break

    if not prev_game:
        return {
            "travel_adjustment": 0.0,
            "timezone_zones_crossed": 0,
            "direction": "none",
            "is_day_after_night": False,
        }

    # Determine previous game location
    prev_was_home = prev_game.get("home_id") == team_id
    if prev_was_home:
        prev_city_team = team_name
    else:
        prev_city_team = prev_game.get("home_name", "")

    # Current game location
    if is_home:
        current_city_team = team_name
    else:
        current_city_team = opponent_name

    # Compute timezone crossing
    tz_diff = compute_timezone_crossing(prev_city_team, current_city_team)

    adjustment = 0.0
    direction = "none"

    # Only apply jet lag for eastward travel of 2+ zones
    if tz_diff >= 2:
        direction = "eastward"
        zones = min(tz_diff, 3)  # Cap at 3 zones
        adjustment = min(zones * EASTWARD_JET_LAG_PER_ZONE, MAX_JET_LAG_ADJUSTMENT)
    elif tz_diff <= -2:
        direction = "westward"
        # Westward travel has minimal effect per research
        adjustment = 0.05

    # Day game after night game check
    is_day_after_night = False
    prev_game_time = prev_game.get("game_datetime", "")
    if prev_game_time and "T" in prev_game_time:
        try:
            hour = int(prev_game_time.split("T")[1][:2])
            # If previous game started at 7pm+ (19:00+ UTC ~ late evening local)
            # and we have a "day" game, apply small penalty
            if hour >= 22:  # UTC late = evening local for US
                is_day_after_night = True
                adjustment += DAY_AFTER_NIGHT_PENALTY
        except (ValueError, IndexError):
            pass

    return {
        "travel_adjustment": round(adjustment, 3),
        "timezone_zones_crossed": abs(tz_diff),
        "direction": direction,
        "is_day_after_night": is_day_after_night,
    }


def get_travel_run_adjustment(
    team_id, team_name, opponent_name, is_home=True, target_date=None
):
    """Simplified interface returning just the run adjustment.

    Positive = more runs expected from the fatigued team's opponents.
    """
    result = compute_travel_fatigue(
        team_id, team_name, opponent_name, is_home, target_date
    )
    return result["travel_adjustment"]
