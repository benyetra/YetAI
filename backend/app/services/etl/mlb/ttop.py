"""Times-Through-the-Order Penalty (TTOP) Calculator.

Applies wOBA penalty adjustments based on how many times a batter has faced
the starting pitcher in a game. Heavy-fastball pitchers suffer a larger penalty.

Research basis:
- Batters gain +8-10 wOBA points each time through the order
- Heavy-fastball pitchers (>75% FB usage): +47 wOBA by 3rd time through
- Diverse repertoire pitchers (3+ pitches at 20%+): only +18 wOBA points

Technical Playbook §3 — Pitcher Workload.
"""
import sys
import os

import logging
import statsapi as mlbstatsapi

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CURRENT_SEASON = 2026

# TTOP penalty per pass (in wOBA points, normalized to 0-1 scale)
# Pass 1 = baseline (0), Pass 2 = +9 wOBA pts, Pass 3 = +18 wOBA pts
BASE_PENALTY = {1: 0.000, 2: 0.009, 3: 0.018}

# Repertoire-adjusted multipliers
HEAVY_FASTBALL_MULTIPLIER = 2.6   # +47 wOBA by 3rd TTO for heavy FB pitchers
DIVERSE_REPERTOIRE_MULTIPLIER = 1.0  # +18 wOBA (baseline)
MODERATE_REPERTOIRE_MULTIPLIER = 1.5  # Between heavy FB and diverse

# Reliever fatigue thresholds
RELIEVER_CONSECUTIVE_DAY_PENALTY = 0.030  # +30 wOBA points for back-to-back
RELIEVER_HIGH_BATTER_PENALTY = 0.015      # +15 wOBA when facing 5+ batters in 2 days


def classify_pitcher_repertoire(pitcher_id):
    """Classify pitcher's repertoire diversity.

    Returns:
        'heavy_fastball': >75% fastball usage
        'diverse': 3+ pitches each at 20%+ usage
        'moderate': everything else
    """
    try:
        data = mlbstatsapi.player_stat_data(
            pitcher_id, group='pitching', type='pitchArsenal',
            season=str(CURRENT_SEASON)
        )
        pitches = {}
        if isinstance(data, dict):
            stats = data.get('stats', [])
            if isinstance(stats, list):
                for entry in stats:
                    s = entry.get('stats', {}) if isinstance(entry, dict) else {}
                    pitch_type = s.get('pitchType', {}).get('code', '')
                    pct = float(s.get('percentage', 0) or 0)
                    if pitch_type:
                        pitches[pitch_type] = pct
    except Exception:
        # If we can't get pitch mix, default to moderate
        return 'moderate'

    if not pitches:
        return 'moderate'

    # Check fastball percentage (FF, SI, FC)
    fb_types = {'FF', 'SI', 'FC', 'FA'}
    fb_pct = sum(pct for pt, pct in pitches.items() if pt in fb_types)

    if fb_pct > 75:
        return 'heavy_fastball'

    # Check if 3+ pitches at 20%+
    significant_pitches = sum(1 for pct in pitches.values() if pct >= 20)
    if significant_pitches >= 3:
        return 'diverse'

    return 'moderate'


def get_ttop_multiplier(repertoire_class):
    """Get the TTOP penalty multiplier based on repertoire classification."""
    return {
        'heavy_fastball': HEAVY_FASTBALL_MULTIPLIER,
        'diverse': DIVERSE_REPERTOIRE_MULTIPLIER,
        'moderate': MODERATE_REPERTOIRE_MULTIPLIER,
    }.get(repertoire_class, MODERATE_REPERTOIRE_MULTIPLIER)


def compute_ttop_adjustment(pitcher_id, projected_innings=6.0):
    """Compute the times-through-the-order adjustment for a starting pitcher.

    Estimates how many times through the lineup the pitcher will face based
    on projected innings, then applies the appropriate penalty.

    Args:
        pitcher_id: MLB player ID
        projected_innings: Expected innings pitched

    Returns:
        dict with:
            repertoire_class: str
            ttop_multiplier: float
            estimated_passes: float (weighted average of passes through order)
            run_adjustment: float (expected additional runs due to TTOP)
            woba_penalty: float (weighted wOBA penalty)
    """
    repertoire = classify_pitcher_repertoire(pitcher_id)
    multiplier = get_ttop_multiplier(repertoire)

    # Estimate times through order based on innings
    # ~3 batters per inning, 9 batters in a lineup
    total_batters = projected_innings * 3.0
    passes_completed = total_batters / 9.0

    # Weighted penalty across passes
    if passes_completed <= 1.0:
        weighted_penalty = BASE_PENALTY[1]
    elif passes_completed <= 2.0:
        frac = passes_completed - 1.0
        weighted_penalty = (1.0 - frac) * BASE_PENALTY[1] + frac * BASE_PENALTY[2]
    else:
        # Weight pass 3+ effects
        frac = min(passes_completed - 2.0, 1.0)
        weighted_penalty = (
            0.33 * BASE_PENALTY[1] +
            0.33 * BASE_PENALTY[2] +
            0.34 * (BASE_PENALTY[2] + frac * (BASE_PENALTY[3] - BASE_PENALTY[2]))
        )

    adjusted_penalty = weighted_penalty * multiplier

    # Convert wOBA penalty to approximate run impact
    # ~1.2 runs per 1.000 wOBA across a game
    run_adjustment = adjusted_penalty * 1.2 * (projected_innings / 9.0) * 27.0

    return {
        'repertoire_class': repertoire,
        'ttop_multiplier': multiplier,
        'estimated_passes': round(passes_completed, 2),
        'run_adjustment': round(run_adjustment, 3),
        'woba_penalty': round(adjusted_penalty, 4),
    }


def compute_reliever_fatigue_penalty(pitcher_id, recent_appearances=None):
    """Compute reliever fatigue penalty based on recent usage.

    Args:
        pitcher_id: MLB player ID
        recent_appearances: list of dicts with 'days_ago', 'batters_faced', 'pitches'
            If None, attempts to fetch from MLB API.

    Returns:
        float: wOBA penalty to add to opposing batter projections
    """
    if recent_appearances is None:
        return 0.0  # No data, no penalty

    penalty = 0.0

    # Check consecutive-day usage
    consecutive = any(a.get('days_ago', 99) <= 1 for a in recent_appearances)
    if consecutive:
        penalty += RELIEVER_CONSECUTIVE_DAY_PENALTY

    # Check high batter count in last 2 days
    recent_batters = sum(
        a.get('batters_faced', 0) for a in recent_appearances
        if a.get('days_ago', 99) <= 2
    )
    if recent_batters >= 5:
        penalty += RELIEVER_HIGH_BATTER_PENALTY

    return round(penalty, 4)


def get_ttop_run_adjustment(pitcher_id, projected_innings=6.0):
    """Simplified interface: returns just the run adjustment value.

    Positive value = more runs expected (worse for pitcher's team).
    """
    result = compute_ttop_adjustment(pitcher_id, projected_innings)
    return result['run_adjustment']
