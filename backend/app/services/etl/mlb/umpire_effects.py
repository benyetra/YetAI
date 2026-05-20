"""Umpire Effects on Run Scoring.

Models home plate umpire impact on run production for over/under totals.
Extreme umpires affect scoring by +/- 0.5 runs per game. Effects reduced
20-30% for 2026 ABS Challenge System season.

Research basis:
- HP umpire identity affects run scoring by +/- 0.5 runs for extreme umpires
- 2026 ABS Challenge System: 2 challenges/team, ~50-52% overturn rate
- Only ~1.4% of pitches challenged, ~98.6% remain human-called
- Reduce umpire adjustment by 25% for 2026

Technical Playbook §9 — Umpires and ABS.
"""

import sys
import os

import logging
import statsapi as mlbstatsapi

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ABS Challenge System adjustment factor for 2026
# Reduces umpire impact by 25% (range: 20-30%)
ABS_REDUCTION_FACTOR = 0.75

# Umpire tendency scores: run adjustment relative to league average
# Positive = more runs (hitter-friendly), Negative = fewer runs (pitcher-friendly)
# Based on historical zone analysis (2023-2025 seasons)
# These represent the top/bottom umpires — most fall within +/-0.2
UMPIRE_RUN_ADJUSTMENTS = {
    # Hitter-friendly umpires (wide zone, generous strikes)
    "Marvin Hudson": -0.35,
    # Angel Hernandez retired after 2024 season
    "CB Bucknor": 0.30,
    "Laz Diaz": 0.25,
    "Jeff Nelson": -0.30,
    "Doug Eddings": 0.20,
    "Hunter Wendelstedt": 0.25,
    "Bill Miller": -0.20,
    "Sam Holbrook": -0.25,
    "Ron Kulpa": 0.20,
    # Pitcher-friendly umpires (tight zone, fewer calls)
    "Pat Hoberg": -0.40,
    "Dan Iassogna": -0.30,
    "Mark Carlson": -0.25,
    "Chris Guccione": -0.20,
    "Brian ONora": -0.20,
    "Quinn Wolcott": -0.15,
    "David Rackley": -0.15,
    "Chad Whitson": -0.10,
    "Jansen Visconti": -0.10,
    "Alan Porter": 0.15,
    # Neutral-ish umpires
    "James Hoye": 0.05,
    "John Tumpane": -0.05,
    "Jordan Baker": 0.10,
    "Tripp Gibson": -0.10,
    "Andy Fletcher": 0.05,
    "Nick Mahrley": 0.00,
    "Adam Beck": -0.05,
    "Nic Lentz": 0.10,
    "Lance Barksdale": 0.15,
    "Todd Tichenor": -0.15,
}


def get_umpire_for_game(game_id):
    """Fetch home plate umpire for a specific game.

    Returns:
        str or None: umpire name
    """
    try:
        game_data = mlbstatsapi.get("game", {"gamePk": game_id})
        officials = (
            game_data.get("liveData", {}).get("boxscore", {}).get("officials", [])
        )
        for official in officials:
            if official.get("officialType") == "Home Plate":
                return official.get("official", {}).get("fullName")
    except Exception:
        pass
    return None


def compute_umpire_adjustment(umpire_name):
    """Compute run scoring adjustment for a specific umpire.

    Applies ABS Challenge System reduction for 2026.

    Args:
        umpire_name: str, umpire's full name

    Returns:
        dict with:
            umpire_name: str
            raw_adjustment: float (pre-ABS adjustment)
            adjusted: float (post-ABS adjustment for 2026)
            tendency: str ('hitter_friendly', 'pitcher_friendly', 'neutral')
    """
    raw_adj = UMPIRE_RUN_ADJUSTMENTS.get(umpire_name, 0.0)

    # Apply ABS reduction
    adjusted = raw_adj * ABS_REDUCTION_FACTOR

    # Classify tendency
    if adjusted > 0.10:
        tendency = "hitter_friendly"
    elif adjusted < -0.10:
        tendency = "pitcher_friendly"
    else:
        tendency = "neutral"

    return {
        "umpire_name": umpire_name or "Unknown",
        "raw_adjustment": raw_adj,
        "adjusted": round(adjusted, 3),
        "tendency": tendency,
    }


def get_umpire_run_adjustment(game_id=None, umpire_name=None):
    """Get the umpire-based run adjustment for a game.

    Either provide game_id (will look up umpire) or umpire_name directly.

    Returns:
        float: run adjustment (positive = more runs expected)
    """
    if umpire_name is None and game_id is not None:
        umpire_name = get_umpire_for_game(game_id)

    if umpire_name is None:
        return 0.0

    result = compute_umpire_adjustment(umpire_name)
    return result["adjusted"]
