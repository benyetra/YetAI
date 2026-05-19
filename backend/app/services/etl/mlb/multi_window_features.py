"""Multi-Window Rolling Feature Engineering.

Computes player performance metrics across multiple lookback windows
(7, 14, 30, 60, 120 games) and exponentially weighted moving averages.
Lets XGBoost determine which window matters most for each split.

Research basis:
- "Beat the Streak" ML project: five lookback windows improved precision
  from 74.2% to 77.2% after feature selection
- EWMA with span=30 outperforms simple rolling by ~4% in MAE
- Using both simultaneously and letting XGBoost arbitrate is superior

Technical Playbook §2 — Multi-Window Features.
"""
import sys
import os

import logging
import statsapi as mlbstatsapi
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CURRENT_SEASON = 2026
WINDOWS = [7, 14, 30, 60, 120]

# League average benchmarks
LEAGUE_AVG_BATTING = {
    'avg': 0.248, 'obp': 0.318, 'slg': 0.402, 'ops': 0.720,
    'k_rate': 0.223, 'bb_rate': 0.082, 'hr_rate': 0.033,
}
LEAGUE_AVG_PITCHING = {
    'era': 4.50, 'k9': 8.5, 'whip': 1.30, 'bb9': 3.2,
}


def fetch_batter_game_logs(batter_id, n_games=120):
    """Fetch recent game logs for a batter.

    Returns list of dicts with per-game stats, most recent first.
    """
    try:
        data = mlbstatsapi.player_stat_data(
            batter_id, group='hitting', type='gameLog',
            season=str(CURRENT_SEASON)
        )
        logs = []
        if isinstance(data, dict):
            stats_list = data.get('stats', [])
            if isinstance(stats_list, list):
                for entry in stats_list:
                    s = entry.get('stats', {}) if isinstance(entry, dict) else {}
                    if not s.get('atBats') and s.get('atBats') != 0:
                        continue
                    logs.append({
                        'date': entry.get('date', ''),
                        'ab': int(s.get('atBats', 0) or 0),
                        'h': int(s.get('hits', 0) or 0),
                        'hr': int(s.get('homeRuns', 0) or 0),
                        'k': int(s.get('strikeOuts', 0) or 0),
                        'bb': int(s.get('baseOnBalls', 0) or 0),
                        'pa': int(s.get('plateAppearances', 0) or 0),
                        'rbi': int(s.get('rbi', 0) or 0),
                        'runs': int(s.get('runs', 0) or 0),
                    })
        # Sort by date descending
        logs.sort(key=lambda x: x.get('date', ''), reverse=True)
        return logs[:n_games]
    except Exception as e:
        logger.warning(f"Failed to fetch game logs for batter {batter_id}: {e}")
        return []


def fetch_pitcher_game_logs(pitcher_id, n_games=30):
    """Fetch recent game logs for a pitcher.

    Returns list of dicts with per-start stats, most recent first.
    """
    try:
        data = mlbstatsapi.player_stat_data(
            pitcher_id, group='pitching', type='gameLog',
            season=str(CURRENT_SEASON)
        )
        logs = []
        if isinstance(data, dict):
            stats_list = data.get('stats', [])
            if isinstance(stats_list, list):
                for entry in stats_list:
                    s = entry.get('stats', {}) if isinstance(entry, dict) else {}
                    ip_str = s.get('inningsPitched', '0') or '0'
                    ip = float(ip_str)
                    if ip <= 0:
                        continue
                    logs.append({
                        'date': entry.get('date', ''),
                        'ip': ip,
                        'k': int(s.get('strikeOuts', 0) or 0),
                        'bb': int(s.get('baseOnBalls', 0) or 0),
                        'h': int(s.get('hits', 0) or 0),
                        'er': int(s.get('earnedRuns', 0) or 0),
                        'hr': int(s.get('homeRuns', 0) or 0),
                        'bf': int(s.get('battersFaced', 0) or max(int(ip * 4), 1)),
                    })
        logs.sort(key=lambda x: x.get('date', ''), reverse=True)
        return logs[:n_games]
    except Exception as e:
        logger.warning(f"Failed to fetch game logs for pitcher {pitcher_id}: {e}")
        return []


def compute_rolling_batting_features(game_logs, windows=None):
    """Compute multi-window rolling features for a batter.

    Args:
        game_logs: list of game log dicts (most recent first)
        windows: list of window sizes (default: [7, 14, 30, 60, 120])

    Returns:
        dict of features keyed by 'batting_{stat}_{window}g'
    """
    if windows is None:
        windows = WINDOWS

    features = {}

    for w in windows:
        subset = game_logs[:w]
        if not subset:
            # Use league averages
            features[f'batting_avg_{w}g'] = LEAGUE_AVG_BATTING['avg']
            features[f'batting_ops_{w}g'] = LEAGUE_AVG_BATTING['ops']
            features[f'batting_k_rate_{w}g'] = LEAGUE_AVG_BATTING['k_rate']
            features[f'batting_hr_rate_{w}g'] = LEAGUE_AVG_BATTING['hr_rate']
            continue

        total_ab = sum(g['ab'] for g in subset)
        total_pa = sum(g['pa'] for g in subset)
        total_h = sum(g['h'] for g in subset)
        total_hr = sum(g['hr'] for g in subset)
        total_k = sum(g['k'] for g in subset)
        total_bb = sum(g['bb'] for g in subset)

        # Batting average
        avg = total_h / max(total_ab, 1)
        features[f'batting_avg_{w}g'] = round(avg, 3)

        # OBP
        obp = (total_h + total_bb) / max(total_pa, 1)
        features[f'batting_obp_{w}g'] = round(obp, 3)

        # OPS (simplified — SLG needs extra base hit detail)
        # Estimate SLG from BA and HR rate
        slg = avg + (total_hr / max(total_ab, 1)) * 3.0
        features[f'batting_ops_{w}g'] = round(obp + slg, 3)

        # K rate
        k_rate = total_k / max(total_pa, 1)
        features[f'batting_k_rate_{w}g'] = round(k_rate, 3)

        # HR rate
        hr_rate = total_hr / max(total_ab, 1)
        features[f'batting_hr_rate_{w}g'] = round(hr_rate, 3)

        # BB rate
        bb_rate = total_bb / max(total_pa, 1)
        features[f'batting_bb_rate_{w}g'] = round(bb_rate, 3)

    return features


def compute_rolling_pitching_features(game_logs, windows=None):
    """Compute multi-window rolling features for a pitcher.

    Args:
        game_logs: list of game log dicts (most recent first)
        windows: list of window sizes in starts

    Returns:
        dict of features keyed by 'pitching_{stat}_{window}s'
    """
    if windows is None:
        # For pitchers, use starts not games (fewer data points)
        windows = [3, 5, 10, 15, 25]

    features = {}

    for w in windows:
        subset = game_logs[:w]
        if not subset:
            features[f'pitching_era_{w}s'] = LEAGUE_AVG_PITCHING['era']
            features[f'pitching_k9_{w}s'] = LEAGUE_AVG_PITCHING['k9']
            features[f'pitching_whip_{w}s'] = LEAGUE_AVG_PITCHING['whip']
            continue

        total_ip = sum(g['ip'] for g in subset)
        total_er = sum(g['er'] for g in subset)
        total_k = sum(g['k'] for g in subset)
        total_bb = sum(g['bb'] for g in subset)
        total_h = sum(g['h'] for g in subset)
        total_hr = sum(g['hr'] for g in subset)

        # ERA
        era = (total_er / max(total_ip, 0.1)) * 9.0
        features[f'pitching_era_{w}s'] = round(era, 2)

        # K/9
        k9 = (total_k / max(total_ip, 0.1)) * 9.0
        features[f'pitching_k9_{w}s'] = round(k9, 2)

        # WHIP
        whip = (total_bb + total_h) / max(total_ip, 0.1)
        features[f'pitching_whip_{w}s'] = round(whip, 3)

        # BB/9
        bb9 = (total_bb / max(total_ip, 0.1)) * 9.0
        features[f'pitching_bb9_{w}s'] = round(bb9, 2)

        # HR/9
        hr9 = (total_hr / max(total_ip, 0.1)) * 9.0
        features[f'pitching_hr9_{w}s'] = round(hr9, 2)

    return features


def compute_ewma_features(game_logs, stat_key, span=30):
    """Compute exponentially weighted moving average for a stat.

    EWMA with span=30 outperforms simple rolling by ~4% in MAE.

    Args:
        game_logs: list of game log dicts (oldest first)
        stat_key: key to extract from each game log
        span: EWMA span parameter

    Returns:
        float: current EWMA value
    """
    if not game_logs:
        return None

    # Reverse to oldest-first for EWMA calculation
    values = [g.get(stat_key, 0) for g in reversed(game_logs)]

    alpha = 2.0 / (span + 1)
    ewma = values[0]
    for v in values[1:]:
        ewma = alpha * v + (1 - alpha) * ewma

    return round(ewma, 4)


def get_batter_multi_window_features(batter_id):
    """Get all multi-window features for a batter.

    Returns dict of rolling window features + EWMA features.
    """
    logs = fetch_batter_game_logs(batter_id)

    if not logs:
        # Return league averages
        features = {}
        for w in WINDOWS:
            features[f'batting_avg_{w}g'] = LEAGUE_AVG_BATTING['avg']
            features[f'batting_ops_{w}g'] = LEAGUE_AVG_BATTING['ops']
            features[f'batting_k_rate_{w}g'] = LEAGUE_AVG_BATTING['k_rate']
            features[f'batting_hr_rate_{w}g'] = LEAGUE_AVG_BATTING['hr_rate']
        features['batting_h_ewma30'] = 1.0
        features['batting_hr_ewma30'] = 0.03
        return features

    features = compute_rolling_batting_features(logs)

    # Add EWMA features
    features['batting_h_ewma30'] = compute_ewma_features(logs, 'h', span=30) or 1.0
    features['batting_hr_ewma30'] = compute_ewma_features(logs, 'hr', span=30) or 0.03
    features['batting_k_ewma30'] = compute_ewma_features(logs, 'k', span=30) or 1.0

    return features


def get_pitcher_multi_window_features(pitcher_id):
    """Get all multi-window features for a pitcher.

    Returns dict of rolling window features + EWMA features.
    """
    logs = fetch_pitcher_game_logs(pitcher_id)

    if not logs:
        features = {}
        for w in [3, 5, 10, 15, 25]:
            features[f'pitching_era_{w}s'] = LEAGUE_AVG_PITCHING['era']
            features[f'pitching_k9_{w}s'] = LEAGUE_AVG_PITCHING['k9']
            features[f'pitching_whip_{w}s'] = LEAGUE_AVG_PITCHING['whip']
        features['pitching_er_ewma10'] = 3.0
        features['pitching_k_ewma10'] = 6.0
        return features

    features = compute_rolling_pitching_features(logs)

    # Add EWMA features
    features['pitching_er_ewma10'] = compute_ewma_features(logs, 'er', span=10) or 3.0
    features['pitching_k_ewma10'] = compute_ewma_features(logs, 'k', span=10) or 6.0
    features['pitching_ip_ewma10'] = compute_ewma_features(logs, 'ip', span=10) or 5.5

    return features
