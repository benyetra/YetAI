"""Statcast Feature Engineering Module.

Computes advanced Statcast-derived features for pitcher and batter evaluation,
including Stuff+ proxy, plate discipline metrics, and fast-stabilizing indicators.

Research basis:
- Stuff+ stabilizes at ~80 pitches (1-2 starts), dramatically faster than ERA (~900 BF)
- SwStr% has R² ≈ 0.72-0.78 with K% (best single predictor)
- Chase rate (O-Swing%) stabilizes at ~50-60 PA (usable in 2 weeks)
- Barrel rate stabilizes at ~50 BIP
- Exit velocity on fly balls/line drives is the "stickiest" Statcast metric

Technical Playbook §1 — Statcast Features.
"""
import sys
import os

import logging
import statsapi as mlbstatsapi

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CURRENT_SEASON = 2026

# League average benchmarks for Statcast metrics
LEAGUE_AVG = {
    'k_rate': 0.223,
    'bb_rate': 0.082,
    'whiff_rate': 0.250,
    'chase_rate': 0.290,
    'barrel_rate': 0.068,
    'hard_hit_rate': 0.380,
    'avg_exit_velo': 88.5,
    'xwoba': 0.315,
    'swstr_pct': 0.110,
    'contact_pct': 0.770,
}

# Stabilization thresholds (PA or BF needed for reliable signal)
STABILIZATION_PA = {
    'chase_rate': 55,       # ~2 weeks
    'k_rate': 60,           # ~2.5 weeks (batters), 70 BF (pitchers)
    'barrel_rate': 50,      # ~50 BIP
    'bb_rate': 120,         # ~5 weeks (batters), 170 BF (pitchers)
    'babip': 820,           # Essentially unreliable within-season
    'batting_avg': 910,     # 1.5 seasons
}


def compute_stuff_plus_proxy(pitcher_id):
    """Compute a Stuff+ proxy score from available StatsAPI data.

    True Stuff+ requires raw pitch tracking data. This proxy uses
    K/9, SwStr%, and walk rate as correlates.

    Stuff+ stabilizes at ~80 pitches (1-2 starts), making it the
    fastest-stabilizing pitcher quality metric.

    Returns:
        dict with:
            stuff_plus_proxy: float (100 = league average)
            k9: float
            whiff_proxy: float
            command_proxy: float
            pitches_thrown: int (estimated)
    """
    try:
        data = mlbstatsapi.player_stat_data(
            pitcher_id, group='pitching', type='season',
            season=str(CURRENT_SEASON)
        )
        stats = {}
        if isinstance(data, dict):
            raw = data.get('stats', [])
            if isinstance(raw, list):
                rec = next((r for r in raw if r.get('season') == str(CURRENT_SEASON)), None)
                stats = rec.get('stats', {}) if rec else {}
    except Exception:
        return {
            'stuff_plus_proxy': 100.0,
            'k9': 8.0,
            'whiff_proxy': 50.0,
            'command_proxy': 50.0,
            'pitches_thrown': 0,
        }

    if not stats:
        return {
            'stuff_plus_proxy': 100.0,
            'k9': 8.0,
            'whiff_proxy': 50.0,
            'command_proxy': 50.0,
            'pitches_thrown': 0,
        }

    ip = float(stats.get('inningsPitched', '0') or '0')
    k = float(stats.get('strikeOuts', 0))
    bb = float(stats.get('baseOnBalls', 0))
    bf = float(stats.get('battersFaced', 0) or (ip * 4.3))
    pitches_est = int(bf * 3.9)  # ~3.9 pitches per PA

    # K/9 component (higher = better stuff)
    k9 = (k / max(ip, 1)) * 9.0 if ip > 0 else 8.0

    # K% as whiff proxy (correlates with SwStr% at R² ≈ 0.72-0.78)
    k_rate = k / max(bf, 1)
    whiff_proxy = (k_rate / LEAGUE_AVG['k_rate']) * 50.0

    # Walk rate as command proxy (lower = better command)
    bb_rate = bb / max(bf, 1)
    command_proxy = (1.0 - bb_rate / max(LEAGUE_AVG['bb_rate'] * 2, 0.01)) * 50.0
    command_proxy = max(0, min(100, command_proxy))

    # Stuff+ proxy: weighted combination
    # K/9 weighted most heavily (correlates best with Stuff+)
    k9_component = (k9 / 8.0) * 100.0  # 100 = league avg K/9
    stuff_proxy = 0.60 * k9_component + 0.25 * whiff_proxy + 0.15 * command_proxy

    return {
        'stuff_plus_proxy': round(stuff_proxy, 1),
        'k9': round(k9, 2),
        'whiff_proxy': round(whiff_proxy, 1),
        'command_proxy': round(command_proxy, 1),
        'pitches_thrown': pitches_est,
    }


def compute_batter_discipline_metrics(batter_id):
    """Compute plate discipline metrics for a batter.

    Focus on chase rate and contact rate — the fastest-stabilizing
    offensive metrics.

    Returns:
        dict with:
            k_rate: float
            bb_rate: float
            iso: float (isolated power)
            discipline_score: float (0-100, 100 = best discipline)
            pa: int
    """
    try:
        data = mlbstatsapi.player_stat_data(
            batter_id, group='hitting', type='season',
            season=str(CURRENT_SEASON)
        )
        stats = {}
        if isinstance(data, dict):
            raw = data.get('stats', [])
            if isinstance(raw, list):
                rec = next((r for r in raw if r.get('season') == str(CURRENT_SEASON)), None)
                stats = rec.get('stats', {}) if rec else {}
    except Exception:
        return _default_discipline()

    if not stats:
        return _default_discipline()

    pa = float(stats.get('plateAppearances', 0) or 0)
    ab = float(stats.get('atBats', 0) or 0)
    k = float(stats.get('strikeOuts', 0) or 0)
    bb = float(stats.get('baseOnBalls', 0) or 0)
    h = float(stats.get('hits', 0) or 0)
    doubles = float(stats.get('doubles', 0) or 0)
    triples = float(stats.get('triples', 0) or 0)
    hr = float(stats.get('homeRuns', 0) or 0)

    if pa < 5:
        return _default_discipline()

    k_rate = k / pa
    bb_rate = bb / pa
    ba = h / max(ab, 1)
    slg = (h - doubles - triples - hr + 2 * doubles + 3 * triples + 4 * hr) / max(ab, 1)
    iso = slg - ba

    # Discipline score: combines walk rate (positive) and K rate (negative)
    # Higher = better discipline
    bb_component = (bb_rate / LEAGUE_AVG['bb_rate']) * 50.0
    k_component = (1.0 - k_rate / max(LEAGUE_AVG['k_rate'] * 1.5, 0.01)) * 50.0
    discipline_score = max(0, min(100, bb_component + k_component))

    return {
        'k_rate': round(k_rate, 3),
        'bb_rate': round(bb_rate, 3),
        'iso': round(iso, 3),
        'discipline_score': round(discipline_score, 1),
        'pa': int(pa),
    }


def _default_discipline():
    """Return default discipline metrics."""
    return {
        'k_rate': LEAGUE_AVG['k_rate'],
        'bb_rate': LEAGUE_AVG['bb_rate'],
        'iso': 0.150,
        'discipline_score': 50.0,
        'pa': 0,
    }


def compute_regression_weight(n_events, stabilization_threshold):
    """Compute Bayesian regression weight based on sample size.

    Formula: weight = n_events / (n_events + stabilization_PA)
    This automatically transitions from prior-heavy to data-heavy.

    Returns:
        float: weight for player data (0-1), complement is league average weight
    """
    return n_events / (n_events + stabilization_threshold)


def regress_stat_to_mean(player_stat, n_events, league_avg, stabilization_threshold):
    """Apply Bayesian regression to mean for a single statistic.

    estimated_talent = (player_stat * n_events + league_avg * stabilization_PA)
                       / (n_events + stabilization_PA)

    This is the standard James-Stein shrinkage approach.
    """
    w = compute_regression_weight(n_events, stabilization_threshold)
    return w * player_stat + (1 - w) * league_avg


def get_pitcher_quality_score(pitcher_id):
    """Get an overall pitcher quality score incorporating Statcast features.

    Returns:
        float: quality score (0-100, where 50 = league average)
    """
    stuff = compute_stuff_plus_proxy(pitcher_id)

    # Regress Stuff+ proxy if few pitches
    pitches = stuff['pitches_thrown']
    if pitches < 300:
        # Regress heavily toward league average (100)
        w = min(pitches / 300.0, 1.0)
        regressed = w * stuff['stuff_plus_proxy'] + (1 - w) * 100.0
    else:
        regressed = stuff['stuff_plus_proxy']

    # Convert to 0-100 scale where 50 = average
    score = 50.0 + (regressed - 100.0) * 0.5
    return round(max(0, min(100, score)), 1)
