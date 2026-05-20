"""Cluster-Based Pitcher-Batter Matchup Model.

Replaces individual BvP stats (which are mostly noise at typical sample sizes)
with cluster-level archetype matching. Classifies pitchers and batters into
archetypes, then uses cluster-level statistics with robust sample sizes.

Research basis:
- MIT Sloan: 15-cluster system shows best matchups ~0.5 runs/inning better than worst
- Individual BvP stats need 50+ PA for K% signal (The Book, FanGraphs, Elias)
- November 2025 arXiv: hierarchical Bayesian matchup models yield ~1 additional win/162

Technical Playbook §4 — Cluster-Based Matchups.
"""

import sys
import os

import logging
import numpy as np
import statsapi as mlbstatsapi

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CURRENT_SEASON = 2026

# Pitcher archetype clusters based on pitch arsenal and velocity
# Each cluster maps to typical offensive outcomes (wOBA against)
PITCHER_CLUSTERS = {
    "power_fastball": {
        "description": "High velo (>95), fastball-heavy",
        "avg_woba_against": 0.295,
        "platoon_factor": 1.05,
    },
    "finesse_control": {
        "description": "Low velo (<92), command-oriented, low walk rate",
        "avg_woba_against": 0.325,
        "platoon_factor": 0.95,
    },
    "breaking_ball_heavy": {
        "description": "High breaking ball usage (>40% SL+CU)",
        "avg_woba_against": 0.310,
        "platoon_factor": 1.12,
    },
    "changeup_specialist": {
        "description": "Heavy changeup usage (>25% CH), pitch tunneling",
        "avg_woba_against": 0.305,
        "platoon_factor": 1.08,
    },
    "sinker_groundball": {
        "description": "Sinker/two-seam heavy, induces groundballs",
        "avg_woba_against": 0.320,
        "platoon_factor": 1.02,
    },
    "mixed_arsenal": {
        "description": "Balanced 3+ pitch mix with no dominant pitch",
        "avg_woba_against": 0.315,
        "platoon_factor": 1.00,
    },
}

# Batter archetype clusters based on approach
BATTER_CLUSTERS = {
    "power_pull": {
        "description": "Pull-heavy, high fly ball rate, high K%",
        "cluster_woba": 0.340,
        "vs_power_adj": -0.010,  # Struggle vs high velo
        "vs_breaking_adj": 0.015,  # Better vs breaking balls
    },
    "contact_spray": {
        "description": "High contact rate, all-fields approach",
        "cluster_woba": 0.320,
        "vs_power_adj": 0.010,  # Handle velo well
        "vs_breaking_adj": 0.005,
    },
    "patient_power": {
        "description": "High walk rate, moderate K%, power when connects",
        "cluster_woba": 0.355,
        "vs_power_adj": 0.005,
        "vs_breaking_adj": 0.010,
    },
    "aggressive_fastball": {
        "description": "Low walk rate, swings early, good on fastballs",
        "cluster_woba": 0.310,
        "vs_power_adj": 0.015,
        "vs_breaking_adj": -0.020,  # Chase breaking balls
    },
    "discipline_slap": {
        "description": "High contact, low power, excellent plate discipline",
        "cluster_woba": 0.295,
        "vs_power_adj": 0.005,
        "vs_breaking_adj": 0.010,
    },
}

# Cluster interaction adjustments (pitcher_cluster -> batter_cluster -> wOBA delta)
CLUSTER_INTERACTIONS = {
    "power_fastball": {
        "power_pull": -0.015,  # Power on power = pitcher advantage
        "contact_spray": 0.010,
        "patient_power": 0.005,
        "aggressive_fastball": 0.020,  # Aggressive batter time fastball
        "discipline_slap": 0.005,
    },
    "finesse_control": {
        "power_pull": 0.020,  # Power hitters crush soft tossers
        "contact_spray": 0.005,
        "patient_power": 0.015,
        "aggressive_fastball": -0.010,
        "discipline_slap": -0.005,
    },
    "breaking_ball_heavy": {
        "power_pull": 0.005,
        "contact_spray": -0.005,
        "patient_power": 0.010,
        "aggressive_fastball": -0.025,  # Chases off-speed
        "discipline_slap": 0.005,
    },
    "changeup_specialist": {
        "power_pull": 0.010,
        "contact_spray": 0.000,
        "patient_power": 0.005,
        "aggressive_fastball": -0.020,
        "discipline_slap": 0.005,
    },
    "sinker_groundball": {
        "power_pull": 0.015,
        "contact_spray": -0.005,
        "patient_power": 0.010,
        "aggressive_fastball": 0.005,
        "discipline_slap": 0.000,
    },
    "mixed_arsenal": {
        "power_pull": 0.005,
        "contact_spray": 0.000,
        "patient_power": 0.005,
        "aggressive_fastball": -0.005,
        "discipline_slap": 0.000,
    },
}


def classify_pitcher_cluster(pitcher_id):
    """Classify pitcher into archetype cluster based on pitch arsenal.

    Uses MLB StatsAPI pitchArsenal data to determine cluster membership.

    Returns:
        str: cluster name from PITCHER_CLUSTERS
    """
    try:
        data = mlbstatsapi.player_stat_data(
            pitcher_id,
            group="pitching",
            type="pitchArsenal",
            season=str(CURRENT_SEASON),
        )
        pitches = {}
        if isinstance(data, dict):
            stats = data.get("stats", [])
            if isinstance(stats, list):
                for entry in stats:
                    s = entry.get("stats", {}) if isinstance(entry, dict) else {}
                    pitch_type = s.get("pitchType", {}).get("code", "")
                    pct = float(s.get("percentage", 0) or 0)
                    if pitch_type:
                        pitches[pitch_type] = pct
    except Exception:
        return "mixed_arsenal"

    if not pitches:
        return "mixed_arsenal"

    # Classify based on pitch mix
    fb_types = {"FF", "SI", "FC", "FA"}
    breaking_types = {"SL", "CU", "KC", "ST", "SV"}
    changeup_types = {"CH", "FS", "SC"}
    sinker_types = {"SI", "FT"}

    fb_pct = sum(pct for pt, pct in pitches.items() if pt in fb_types)
    breaking_pct = sum(pct for pt, pct in pitches.items() if pt in breaking_types)
    changeup_pct = sum(pct for pt, pct in pitches.items() if pt in changeup_types)
    sinker_pct = sum(pct for pt, pct in pitches.items() if pt in sinker_types)

    # Get velocity if available (from season stats)
    avg_velo = None
    try:
        season_data = mlbstatsapi.player_stat_data(
            pitcher_id, group="pitching", type="season", season=str(CURRENT_SEASON)
        )
        if isinstance(season_data, dict):
            stats_list = season_data.get("stats", [])
            if isinstance(stats_list, list):
                for s in stats_list:
                    st = s.get("stats", {})
                    if "strikeOuts" in st:
                        # Estimate velo from K/9 as proxy (higher K/9 correlates with higher velo)
                        ip = float(st.get("inningsPitched", "0") or "0")
                        k = float(st.get("strikeOuts", 0))
                        k9 = (k / max(ip, 1)) * 9.0 if ip > 0 else 8.0
                        # Rough proxy: K/9 of 12+ often indicates high velo
                        if k9 >= 11:
                            avg_velo = 96.0
                        elif k9 >= 9:
                            avg_velo = 94.0
                        else:
                            avg_velo = 91.0
                        break
    except Exception:
        avg_velo = 93.0

    if avg_velo is None:
        avg_velo = 93.0

    # Decision tree for cluster classification
    if sinker_pct >= 25:
        return "sinker_groundball"

    if fb_pct >= 65 and avg_velo >= 95:
        return "power_fastball"

    if changeup_pct >= 25:
        return "changeup_specialist"

    if breaking_pct >= 40:
        return "breaking_ball_heavy"

    if fb_pct >= 60 and avg_velo < 92:
        return "finesse_control"

    return "mixed_arsenal"


def classify_batter_cluster(batter_id):
    """Classify batter into archetype cluster based on approach metrics.

    Uses season stats to infer approach type.

    Returns:
        str: cluster name from BATTER_CLUSTERS
    """
    try:
        data = mlbstatsapi.player_stat_data(
            batter_id, group="hitting", type="season", season=str(CURRENT_SEASON)
        )
        stats = {}
        if isinstance(data, dict):
            raw = data.get("stats", [])
            if isinstance(raw, list):
                rec = next(
                    (r for r in raw if r.get("season") == str(CURRENT_SEASON)), None
                )
                stats = rec.get("stats", {}) if rec else {}
    except Exception:
        return "contact_spray"

    if not stats:
        return "contact_spray"

    ab = float(stats.get("atBats", 0) or 0)
    pa = float(stats.get("plateAppearances", 0) or 0)
    k = float(stats.get("strikeOuts", 0) or 0)
    bb = float(stats.get("baseOnBalls", 0) or 0)
    hr = float(stats.get("homeRuns", 0) or 0)
    h = float(stats.get("hits", 0) or 0)

    if pa < 10:
        return "contact_spray"

    k_rate = k / pa
    bb_rate = bb / pa
    hr_rate = hr / max(ab, 1)
    ba = h / max(ab, 1)

    # Classification rules
    if hr_rate >= 0.045 and k_rate >= 0.25:
        return "power_pull"

    if bb_rate >= 0.12 and hr_rate >= 0.030:
        return "patient_power"

    if k_rate <= 0.15 and bb_rate <= 0.06:
        return "aggressive_fastball"

    if k_rate <= 0.18 and ba >= 0.260:
        return "contact_spray"

    if bb_rate >= 0.10 and k_rate <= 0.20:
        return "discipline_slap"

    return "contact_spray"


def compute_cluster_matchup_adjustment(pitcher_id, batter_ids=None):
    """Compute cluster-based matchup adjustment for a lineup vs pitcher.

    Args:
        pitcher_id: MLB pitcher ID
        batter_ids: list of batter IDs in the lineup (optional)

    Returns:
        dict with:
            pitcher_cluster: str
            avg_matchup_adj: float (wOBA adjustment for lineup vs this pitcher type)
            run_impact: float (estimated run adjustment)
            batter_clusters: list of (batter_id, cluster) tuples
    """
    pitcher_cluster = classify_pitcher_cluster(pitcher_id)

    if not batter_ids:
        return {
            "pitcher_cluster": pitcher_cluster,
            "avg_matchup_adj": 0.0,
            "run_impact": 0.0,
            "batter_clusters": [],
        }

    batter_clusters = []
    matchup_adjs = []

    for bid in batter_ids:
        batter_cluster = classify_batter_cluster(bid)
        batter_clusters.append((bid, batter_cluster))

        # Get interaction adjustment
        interaction = CLUSTER_INTERACTIONS.get(pitcher_cluster, {})
        adj = interaction.get(batter_cluster, 0.0)

        # Add batter cluster base adjustment
        batter_info = BATTER_CLUSTERS.get(batter_cluster, {})
        if pitcher_cluster in ("power_fastball",):
            adj += batter_info.get("vs_power_adj", 0.0)
        elif pitcher_cluster in ("breaking_ball_heavy", "changeup_specialist"):
            adj += batter_info.get("vs_breaking_adj", 0.0)

        matchup_adjs.append(adj)

    avg_adj = float(np.mean(matchup_adjs)) if matchup_adjs else 0.0

    # Convert wOBA adjustment to run impact
    # ~1.2 runs per 1.000 wOBA across a full game (27 PA)
    run_impact = avg_adj * 1.2 * 27.0

    return {
        "pitcher_cluster": pitcher_cluster,
        "avg_matchup_adj": round(avg_adj, 4),
        "run_impact": round(run_impact, 3),
        "batter_clusters": batter_clusters,
    }


def get_matchup_run_adjustment(pitcher_id, batter_ids=None):
    """Simplified interface returning just the run impact value.

    Positive = more runs expected (better for offense).
    """
    result = compute_cluster_matchup_adjustment(pitcher_id, batter_ids)
    return result["run_impact"]
