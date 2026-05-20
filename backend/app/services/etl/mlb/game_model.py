"""MLB Game-Level XGBoost Model.

Trains and predicts game-level outcomes: win probability and projected run totals.
Uses features from existing player-prop models, bullpen fatigue, weather, park factors,
injury tracker, and team performance metrics.

PRD v2.0 §6.1 Layer 2 — Gradient Boosted Game Model.
"""

import sys
import os

import argparse
import logging
import math
import pickle
import sqlite3
from datetime import date, datetime, timedelta
from io import BytesIO

import numpy as np
import pandas as pd
import requests
import statsapi as mlbstatsapi
from sklearn.linear_model import ElasticNet, LogisticRegression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import brier_score_loss, mean_absolute_error
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier, XGBRegressor

try:
    from tqdm import tqdm
except ImportError:

    def tqdm(x, **kwargs):  # graceful no-op fallback
        return x


try:
    from catboost import CatBoostClassifier, CatBoostRegressor

    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

from app.services.etl.mlb import historical_training_backfill as htb
from app.models.predictions_models import (
    BullpenFatigue,
    Weather,
    BlowoutChances,
    GameProjections,
)

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.bullpen_fatigue import get_team_fatigue
from app.services.etl.mlb.injury_tracker import get_team_injury_impact
from app.services.etl.mlb.odds_utils import american_to_break_even_prob
from app.services.etl.mlb.weather_enhanced import (
    compute_weather_run_adjustment,
    get_dynamic_park_factor,
)
from app.services.etl.mlb.ttop import compute_ttop_adjustment
from app.services.etl.mlb.umpire_effects import get_umpire_run_adjustment
from app.services.etl.mlb.travel_fatigue import get_travel_run_adjustment
from app.services.etl.mlb.statcast_features import get_pitcher_quality_score

try:
    import boto3

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CURRENT_SEASON = date.today().year
S3_BUCKET = "yetibets"
WIN_MODEL_S3_KEY = "mlb/game_model_win.pkl"
TOTAL_MODEL_S3_KEY = "mlb/game_model_total.pkl"
WIN_MODEL_LOCAL = os.path.join(os.path.dirname(__file__), "game_model_win.pkl")
TOTAL_MODEL_LOCAL = os.path.join(os.path.dirname(__file__), "game_model_total.pkl")
WIN_CALIBRATOR_LOCAL = os.path.join(
    os.path.dirname(__file__), "game_model_win_calibrator.pkl"
)
WIN_CALIBRATOR_S3_KEY = "mlb/game_model_win_calibrator.pkl"
TRAINING_CACHE_DB = os.path.join(
    os.path.dirname(__file__), "training_features_cache.db"
)

# Venue name -> park_id code used by PARK_FACTOR_MAP. Module-level constant so
# the historical training pipeline can resolve venue strings without depending
# on `get_venue_park_factor`'s local map.
VENUE_PARK_ID_MAP = {
    "Chase Field": "ari",
    "Truist Park": "atl",
    "Oriole Park at Camden Yards": "bal",
    "Fenway Park": "bos",
    "Wrigley Field": "chc",
    "Guaranteed Rate Field": "chw",
    "Great American Ball Park": "cin",
    "Progressive Field": "cle",
    "Coors Field": "col",
    "Comerica Park": "det",
    "Minute Maid Park": "hou",
    "Kauffman Stadium": "kc",
    "Angel Stadium": "laa",
    "Dodger Stadium": "lad",
    "loanDepot park": "mia",
    "American Family Field": "mil",
    "Target Field": "min",
    "Citi Field": "nym",
    "Yankee Stadium": "nyy",
    "Sutter Health Park": "oak",
    "Oakland Coliseum": "oak",
    "Citizens Bank Park": "phi",
    "PNC Park": "pit",
    "Petco Park": "sd",
    "Oracle Park": "sf",
    "T-Mobile Park": "sea",
    "Busch Stadium": "stl",
    "Tropicana Field": "tb",
    "Globe Life Field": "tex",
    "Rogers Centre": "tor",
    "Nationals Park": "wsh",
}

# Park factors (loaded from S3 or local)
PARK_FACTORS_CSV = "s3://yetibets/mlb/park_factors.csv"
PARK_FACTOR_MAP = {}

# Home field advantage constant
HOME_FIELD_EDGE = 0.04

# Columns built at inference / in training rows but excluded from ML until backfilled.
DEFERRED_FEATURE_COLS = (
    "home_field",  # structurally 1.0 in training
    "rest_differential",  # ~92% neutral 0.0 in historical backfill
    "home_ttop_adj",
    "away_ttop_adj",
    "umpire_run_adj",
    "home_travel_adj",
    "away_travel_adj",
    "home_pitcher_quality",
    "away_pitcher_quality",
)

# Feature columns used for ensemble training and prediction vectors.
FEATURE_COLS = [
    "home_starter_era",
    "away_starter_era",
    "home_starter_k9",
    "away_starter_k9",
    "home_starter_whip",
    "away_starter_whip",
    "home_lineup_ops",
    "away_lineup_ops",
    "home_bullpen_fatigue",
    "away_bullpen_fatigue",
    "park_factor",
    "temperature",
    "wind_speed",
    "home_recent_runs_avg",
    "away_recent_runs_avg",
    "home_recent_runs_allowed_avg",
    "away_recent_runs_allowed_avg",
    "injury_impact_home",
    "injury_impact_away",
    "weather_run_adj",
]

# Fast walk-forward / eval training — stronger regularization vs in-sample overfit.
FAST_XGB_WIN_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.08,
    "subsample": 0.75,
    "colsample_bytree": 0.75,
    "min_child_weight": 8,
    "reg_alpha": 0.3,
    "reg_lambda": 1.0,
    "gamma": 0.1,
}
FAST_XGB_TOTAL_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.08,
    "subsample": 0.75,
    "colsample_bytree": 0.75,
    "min_child_weight": 8,
    "reg_alpha": 0.3,
    "reg_lambda": 1.0,
    "gamma": 0.1,
}

# Training-row values that indicate a feature was not backfilled (for coverage reports).
FEATURE_NEUTRAL_VALUES = {
    "home_bullpen_fatigue": 0.5,
    "away_bullpen_fatigue": 0.5,
    "temperature": 72.0,
    "wind_speed": 5.0,
    "rest_differential": 0.0,
    "home_field": 1.0,
    "injury_impact_home": 0.0,
    "injury_impact_away": 0.0,
    "weather_run_adj": 0.0,
    "home_ttop_adj": 0.0,
    "away_ttop_adj": 0.0,
    "umpire_run_adj": 0.0,
    "home_travel_adj": 0.0,
    "away_travel_adj": 0.0,
    "home_pitcher_quality": 50.0,
    "away_pitcher_quality": 50.0,
}

_ENSEMBLE_META_KEYS = frozenset({"weights", "weights_default", "weight_tuning"})


def _iter_ensemble_models(ensemble):
    """Yield (name, model) pairs, skipping metadata keys."""
    for name, model in ensemble.items():
        if name in _ENSEMBLE_META_KEYS or model is None:
            continue
        yield name, model


def feature_coverage_report(df):
    """Fraction of rows still at neutral training defaults per feature."""
    n = max(len(df), 1)
    rows = []
    for col in FEATURE_COLS:
        if col not in df.columns:
            continue
        neutral = FEATURE_NEUTRAL_VALUES.get(col)
        series = df[col]
        if neutral is not None:
            at_default = (series == neutral) | series.isna()
            pct_default = float(at_default.mean())
        else:
            pct_default = None
        rows.append(
            {
                "feature": col,
                "pct_at_neutral_default": pct_default,
                "std": float(series.std()) if series.notna().any() else 0.0,
                "mean": float(series.mean()) if series.notna().any() else None,
            }
        )
    rows.sort(
        key=lambda r: (
            r["pct_at_neutral_default"] is None,
            -(r["pct_at_neutral_default"] or 0),
        ),
    )
    return {"n_rows": int(len(df)), "features": rows}


def load_park_factors():
    """Load park factor map from S3 or local CSV."""
    global PARK_FACTOR_MAP
    try:
        if HAS_BOTO3:
            s3 = boto3.client("s3")
            obj = s3.get_object(Bucket=S3_BUCKET, Key="mlb/park_factors.csv")
            df = pd.read_csv(BytesIO(obj["Body"].read()))
        else:
            local_path = os.path.join(os.path.dirname(__file__), "park_factors.csv")
            df = pd.read_csv(local_path)
        raw_map = {row["park_id"]: row["hr_factor"] for _, row in df.iterrows()}
        # Normalize: if values are on 100-scale (e.g., 98, 105), convert to 1.0-scale
        sample = list(raw_map.values())[:5]
        if sample and all(v > 10 for v in sample):
            PARK_FACTOR_MAP = {k: round(v / 100.0, 4) for k, v in raw_map.items()}
            logger.info(
                f"Loaded {len(PARK_FACTOR_MAP)} park factors (normalized from 100-scale)"
            )
        else:
            PARK_FACTOR_MAP = raw_map
            logger.info(f"Loaded {len(PARK_FACTOR_MAP)} park factors")
    except Exception as e:
        logger.warning(f"Could not load park factors: {e}")
        PARK_FACTOR_MAP = {}


def _parse_pitcher_season_stats(data, season):
    """Parse pitcher stats from MLB-StatsAPI response for a given season."""
    stats = {}
    if isinstance(data, dict):
        raw = data.get("stats")
        if isinstance(raw, list):
            rec = next((r for r in raw if r.get("season") == str(season)), None)
            stats = rec.get("stats", {}) if rec else {}
        elif isinstance(raw, dict):
            stats = raw
    elif isinstance(data, list):
        rec = next((r for r in data if r.get("season") == str(season)), None)
        stats = rec.get("stats", {}) if rec else {}
    return stats


def get_pitcher_stats(pitcher_id):
    """Fetch pitcher's season stats (ERA, K/9, WHIP) from MLB-StatsAPI.

    Early-season fallback: if the current season has <10 IP, blends current
    stats with previous season stats to avoid pure-default predictions on
    Opening Day and throughout April.
    """
    defaults = {"era": 4.50, "k9": 8.0, "whip": 1.35}
    if not pitcher_id:
        return defaults

    def _extract_stats(raw_stats):
        era = float(raw_stats.get("era", 0) or 0)
        ip = float(raw_stats.get("inningsPitched", "0") or "0")
        k = float(raw_stats.get("strikeOuts", 0) or 0)
        bb = float(raw_stats.get("baseOnBalls", 0) or 0)
        h = float(raw_stats.get("hits", 0) or 0)
        k9 = (k / max(ip, 1)) * 9.0
        whip = (bb + h) / max(ip, 1)
        return {"era": era, "k9": round(k9, 2), "whip": round(whip, 3), "ip": ip}

    try:
        # Try current season first
        data = mlbstatsapi.player_stat_data(
            pitcher_id, group="pitching", type="season", season=str(CURRENT_SEASON)
        )
        current_raw = _parse_pitcher_season_stats(data, CURRENT_SEASON)
        current = _extract_stats(current_raw) if current_raw else None

        # Early-season fallback: if <10 IP this season, use previous season
        if current is None or current["ip"] < 10:
            prev_data = mlbstatsapi.player_stat_data(
                pitcher_id,
                group="pitching",
                type="season",
                season=str(CURRENT_SEASON - 1),
            )
            prev_raw = _parse_pitcher_season_stats(prev_data, CURRENT_SEASON - 1)
            prev = _extract_stats(prev_raw) if prev_raw else None

            if prev and prev["ip"] >= 20:
                if current and current["ip"] >= 1:
                    # Blend: weight current stats by IP fraction (max 50% at 10 IP)
                    w = min(current["ip"] / 20.0, 0.5)
                    return {
                        "era": round(w * current["era"] + (1 - w) * prev["era"], 2),
                        "k9": round(w * current["k9"] + (1 - w) * prev["k9"], 2),
                        "whip": round(w * current["whip"] + (1 - w) * prev["whip"], 3),
                    }
                else:
                    # No current stats at all (Opening Day) — use prior season
                    return {"era": prev["era"], "k9": prev["k9"], "whip": prev["whip"]}

        if current and current["ip"] >= 1:
            return {"era": current["era"], "k9": current["k9"], "whip": current["whip"]}

        return defaults
    except Exception as e:
        logger.warning(f"Failed to get pitcher stats for {pitcher_id}: {e}")
        return defaults


def _fetch_team_hitting_for_season(team_id, season):
    """Fetch team hitting stats for a specific season. Returns dict or None."""
    try:
        url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?season={season}&group=hitting&stats=season"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if "stats" in data and data["stats"]:
            splits = data["stats"][0].get("splits", [])
            if splits:
                stat = splits[0].get("stat", {})
                games = max(int(stat.get("gamesPlayed", 1)), 1)
                runs = int(stat.get("runs", 0))
                ops = float(stat.get("ops", 0.720))
                return {
                    "ops": ops,
                    "runs_per_game": round(runs / games, 2),
                    "games": games,
                }
    except Exception:
        pass
    return None


def get_team_hitting_stats(team_id):
    """Fetch team's season hitting stats (OPS, runs/game).

    Early-season fallback: if <10 games played this season, uses previous
    season stats to avoid pure defaults on Opening Day.
    """
    defaults = {"ops": 0.720, "runs_per_game": 4.5, "runs_allowed_per_game": 4.5}
    try:
        current = _fetch_team_hitting_for_season(team_id, CURRENT_SEASON)

        if current is None or current["games"] < 10:
            prev = _fetch_team_hitting_for_season(team_id, CURRENT_SEASON - 1)
            if prev and prev["games"] >= 50:
                if current and current["games"] >= 3:
                    w = min(current["games"] / 20.0, 0.5)
                    return {
                        "ops": round(w * current["ops"] + (1 - w) * prev["ops"], 3),
                        "runs_per_game": round(
                            w * current["runs_per_game"]
                            + (1 - w) * prev["runs_per_game"],
                            2,
                        ),
                        "runs_allowed_per_game": defaults["runs_allowed_per_game"],
                    }
                else:
                    return {
                        "ops": prev["ops"],
                        "runs_per_game": prev["runs_per_game"],
                        "runs_allowed_per_game": defaults["runs_allowed_per_game"],
                    }

        if current:
            return {
                "ops": current["ops"],
                "runs_per_game": current["runs_per_game"],
                "runs_allowed_per_game": defaults["runs_allowed_per_game"],
            }
    except Exception as e:
        logger.warning(f"Failed to get team hitting stats for {team_id}: {e}")

    return defaults


def _fetch_team_pitching_for_season(team_id, season):
    """Fetch team pitching stats for a specific season. Returns (ra_per_game, games) or None."""
    try:
        url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?season={season}&group=pitching&stats=season"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if "stats" in data and data["stats"]:
            splits = data["stats"][0].get("splits", [])
            if splits:
                stat = splits[0].get("stat", {})
                games = max(int(stat.get("gamesPlayed", 1)), 1)
                runs = int(stat.get("runs", 0))
                return round(runs / games, 2), games
    except Exception:
        pass
    return None


def get_team_pitching_stats(team_id):
    """Fetch team's season pitching stats (runs allowed/game).

    Early-season fallback: if <10 games this season, uses previous season.
    """
    try:
        result = _fetch_team_pitching_for_season(team_id, CURRENT_SEASON)

        if result is None or result[1] < 10:
            prev = _fetch_team_pitching_for_season(team_id, CURRENT_SEASON - 1)
            if prev and prev[1] >= 50:
                if result and result[1] >= 3:
                    w = min(result[1] / 20.0, 0.5)
                    return round(w * result[0] + (1 - w) * prev[0], 2)
                else:
                    return prev[0]

        if result:
            return result[0]
    except Exception:
        pass
    return 4.5


def get_weather_for_venue(venue_name, target_date=None):
    """Retrieve weather data from the Weather table."""
    try:
        weather = (
            db_session.query(Weather).filter(Weather.venue_name == venue_name).first()
        )
        if weather:
            return {
                "temperature": float(weather.temperature or 72),
                "wind_speed": float(weather.wind_speed or 5),
            }
    except Exception:
        pass
    return {"temperature": 72.0, "wind_speed": 5.0}


def get_venue_park_factor(venue_name):
    """Look up park factor for a venue. Returns 1.0 as neutral."""
    # Map common venue names to park_id codes
    venue_map = {
        "Chase Field": "ari",
        "Truist Park": "atl",
        "Oriole Park at Camden Yards": "bal",
        "Fenway Park": "bos",
        "Wrigley Field": "chc",
        "Guaranteed Rate Field": "chw",
        "Great American Ball Park": "cin",
        "Progressive Field": "cle",
        "Coors Field": "col",
        "Comerica Park": "det",
        "Minute Maid Park": "hou",
        "Kauffman Stadium": "kc",
        "Angel Stadium": "laa",
        "Dodger Stadium": "lad",
        "loanDepot park": "mia",
        "American Family Field": "mil",
        "Target Field": "min",
        "Citi Field": "nym",
        "Yankee Stadium": "nyy",
        "Sutter Health Park": "oak",
        "Oakland Coliseum": "oak",
        "Citizens Bank Park": "phi",
        "PNC Park": "pit",
        "Petco Park": "sd",
        "Oracle Park": "sf",
        "T-Mobile Park": "sea",
        "Busch Stadium": "stl",
        "Tropicana Field": "tb",
        "Globe Life Field": "tex",
        "Rogers Centre": "tor",
        "Nationals Park": "wsh",
    }
    park_id = venue_map.get(venue_name)
    if park_id and park_id in PARK_FACTOR_MAP:
        return PARK_FACTOR_MAP[park_id]
    return 1.0


def _compute_rest_differential(game_info):
    """Compute rest days differential (home - away).

    Positive = home team is more rested. Looks at yesterday's schedule
    to determine if each team played.
    """
    try:
        today = date.today()
        yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        two_days = (today - timedelta(days=2)).strftime("%Y-%m-%d")

        home_id = game_info.get("home_id")
        away_id = game_info.get("away_id")

        def _days_since_last_game(team_id):
            for days_back in range(1, 5):
                check_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
                sched = mlbstatsapi.schedule(date=check_date, team=team_id)
                for g in sched:
                    if g.get("status") in ("Final", "Game Over", "Completed Early"):
                        return days_back
            return 1  # Default: played yesterday

        home_rest = _days_since_last_game(home_id)
        away_rest = _days_since_last_game(away_id)
        return float(home_rest - away_rest)
    except Exception:
        return 0.0


def build_game_features(game_info):
    """Build feature vector for a single game from live data sources.

    Args:
        game_info: dict with game_id, home_name, away_name, home_id, away_id,
                   home_probable_pitcher, away_probable_pitcher, venue_name, etc.

    Returns:
        dict of feature values or None if critical data is missing.
    """
    home_id = game_info.get("home_id")
    away_id = game_info.get("away_id")
    home_pid = game_info.get("home_pitcher_id")
    away_pid = game_info.get("away_pitcher_id")
    venue = game_info.get("venue_name", "")

    # Pitcher stats
    home_p = get_pitcher_stats(home_pid)
    away_p = get_pitcher_stats(away_pid)

    # Team hitting
    home_hit = get_team_hitting_stats(home_id)
    away_hit = get_team_hitting_stats(away_id)

    # Team pitching (runs allowed)
    home_ra = get_team_pitching_stats(home_id)
    away_ra = get_team_pitching_stats(away_id)

    # Bullpen fatigue
    home_fatigue = get_team_fatigue(home_id)
    away_fatigue = get_team_fatigue(away_id)

    # Weather
    weather = get_weather_for_venue(venue)

    # Park factor
    pf = get_venue_park_factor(venue)

    # Injury impact
    home_injury = get_team_injury_impact(home_id)
    away_injury = get_team_injury_impact(away_id)

    # Enhanced weather model (air density + wind direction)
    try:
        weather_result = compute_weather_run_adjustment(
            temperature_f=weather["temperature"],
            wind_speed_mph=weather["wind_speed"],
            wind_direction_deg=weather.get("wind_direction", 225),
            humidity_pct=weather.get("humidity", 50),
            venue_name=venue,
        )
        weather_run_adj = weather_result["total_adjustment"]
        # Dynamic park factor combining static + weather
        dynamic_pf = get_dynamic_park_factor(venue, pf, weather_run_adj)
    except Exception:
        weather_run_adj = 0.0
        dynamic_pf = pf

    # TTOP adjustments
    try:
        home_ttop = compute_ttop_adjustment(home_pid)
        away_ttop = compute_ttop_adjustment(away_pid)
    except Exception:
        home_ttop = {"run_adjustment": 0.0}
        away_ttop = {"run_adjustment": 0.0}

    # Umpire effects
    umpire_adj = 0.0
    try:
        game_id = game_info.get("game_id")
        if game_id:
            umpire_adj = get_umpire_run_adjustment(game_id=game_id)
    except Exception:
        pass

    # Travel fatigue
    try:
        home_travel = get_travel_run_adjustment(
            home_id,
            game_info.get("home_name", ""),
            game_info.get("away_name", ""),
            is_home=True,
        )
        away_travel = get_travel_run_adjustment(
            away_id,
            game_info.get("away_name", ""),
            game_info.get("home_name", ""),
            is_home=False,
        )
    except Exception:
        home_travel = 0.0
        away_travel = 0.0

    # Pitcher quality (Stuff+ proxy)
    try:
        home_pq = get_pitcher_quality_score(home_pid) if home_pid else 50.0
        away_pq = get_pitcher_quality_score(away_pid) if away_pid else 50.0
    except Exception:
        home_pq = 50.0
        away_pq = 50.0

    features = {
        "home_starter_era": home_p["era"],
        "away_starter_era": away_p["era"],
        "home_starter_k9": home_p["k9"],
        "away_starter_k9": away_p["k9"],
        "home_starter_whip": home_p["whip"],
        "away_starter_whip": away_p["whip"],
        "home_lineup_ops": home_hit["ops"],
        "away_lineup_ops": away_hit["ops"],
        "home_bullpen_fatigue": home_fatigue,
        "away_bullpen_fatigue": away_fatigue,
        "park_factor": dynamic_pf,
        "temperature": weather["temperature"],
        "wind_speed": weather["wind_speed"],
        "home_recent_runs_avg": home_hit["runs_per_game"],
        "away_recent_runs_avg": away_hit["runs_per_game"],
        "home_recent_runs_allowed_avg": home_ra,
        "away_recent_runs_allowed_avg": away_ra,
        "rest_differential": _compute_rest_differential(game_info),
        "home_field": 1.0,
        "injury_impact_home": home_injury,
        "injury_impact_away": away_injury,
        # Technical Playbook features
        "weather_run_adj": weather_run_adj,
        "home_ttop_adj": home_ttop["run_adjustment"],
        "away_ttop_adj": away_ttop["run_adjustment"],
        "umpire_run_adj": umpire_adj,
        "home_travel_adj": home_travel,
        "away_travel_adj": away_travel,
        "home_pitcher_quality": home_pq,
        "away_pitcher_quality": away_pq,
    }

    return features


def predict_win_probability_heuristic(features):
    """Heuristic win probability when no trained model is available.

    Uses a logistic function on the difference between team strengths,
    following the approach in mlb_ev.py. The core idea: higher OPS against
    a worse opposing pitcher (higher ERA) creates an advantage.
    """
    K_LOGISTIC = 3.0

    h_ops = features["home_lineup_ops"]
    a_ops = features["away_lineup_ops"]
    h_era = features["home_starter_era"]
    a_era = features["away_starter_era"]

    # Team strength: OPS advantage + opposing pitcher weakness (higher ERA = worse)
    # Normalize ERA around league-average 4.50
    h_strength = (h_ops - 0.720) * 5.0 + (a_era - 4.50) * 0.15
    a_strength = (a_ops - 0.720) * 5.0 + (h_era - 4.50) * 0.15

    diff = h_strength - a_strength

    # Bullpen fatigue adjustment (fatigued bullpen = worse for that team)
    diff -= (features["home_bullpen_fatigue"] - 0.5) * 0.15
    diff += (features["away_bullpen_fatigue"] - 0.5) * 0.15

    # Injury adjustment
    diff -= features["injury_impact_home"] * 0.15
    diff += features["injury_impact_away"] * 0.15

    # Park factor (>1.0 = more runs, slight home advantage)
    diff += (features["park_factor"] - 1.0) * 0.3

    # TTOP adjustment (higher penalty = worse for that pitcher's team)
    diff += features.get("away_ttop_adj", 0.0) * 0.05
    diff -= features.get("home_ttop_adj", 0.0) * 0.05

    # Pitcher quality (higher = better for that team)
    diff += (features.get("home_pitcher_quality", 50) - 50) * 0.005
    diff -= (features.get("away_pitcher_quality", 50) - 50) * 0.005

    # Travel fatigue (fatigued team = disadvantage)
    diff -= features.get("home_travel_adj", 0.0) * 0.10
    diff += features.get("away_travel_adj", 0.0) * 0.10

    base = 1.0 / (1.0 + math.exp(-diff * K_LOGISTIC))
    home_prob = min(0.95, max(0.05, base + HOME_FIELD_EDGE))

    return round(home_prob, 4)


def predict_total_runs_heuristic(features):
    """Heuristic run total projection when no trained model is available.

    Combines team run averages, pitcher quality, and park factor.
    """
    home_runs_est = features["home_recent_runs_avg"]
    away_runs_est = features["away_recent_runs_avg"]

    # Adjust for pitcher quality (better pitcher = fewer runs)
    home_pitcher_adj = (
        4.50 - features["away_starter_era"]
    ) * 0.3  # Away pitcher faces home team
    away_pitcher_adj = (4.50 - features["home_starter_era"]) * 0.3

    home_runs_est = max(0.5, home_runs_est - home_pitcher_adj)
    away_runs_est = max(0.5, away_runs_est - away_pitcher_adj)

    # Park factor
    pf = features["park_factor"]
    total = (home_runs_est + away_runs_est) * pf

    # Bullpen fatigue adds runs
    total += (features["home_bullpen_fatigue"] - 0.5) * 0.5
    total += (features["away_bullpen_fatigue"] - 0.5) * 0.5

    # Enhanced weather adjustment (replaces simple temperature check)
    weather_adj = features.get("weather_run_adj", 0.0)
    total += weather_adj

    # Umpire run adjustment
    total += features.get("umpire_run_adj", 0.0)

    # TTOP adjustments (more runs expected as pitcher degrades)
    total += features.get("home_ttop_adj", 0.0) * 0.3
    total += features.get("away_ttop_adj", 0.0) * 0.3

    return round(max(total, 3.0), 1)


def load_model(model_type="win"):
    """Load trained model from local path or S3."""
    local_path = WIN_MODEL_LOCAL if model_type == "win" else TOTAL_MODEL_LOCAL
    s3_key = WIN_MODEL_S3_KEY if model_type == "win" else TOTAL_MODEL_S3_KEY

    # Try local first
    if os.path.exists(local_path):
        with open(local_path, "rb") as f:
            return pickle.load(f)

    # Try S3
    if HAS_BOTO3:
        try:
            s3 = boto3.client("s3")
            obj = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
            return pickle.load(BytesIO(obj["Body"].read()))
        except Exception:
            pass

    return None


def save_model(model, model_type="win"):
    """Save trained model to local path and S3."""
    local_path = WIN_MODEL_LOCAL if model_type == "win" else TOTAL_MODEL_LOCAL
    s3_key = WIN_MODEL_S3_KEY if model_type == "win" else TOTAL_MODEL_S3_KEY

    # Save local
    with open(local_path, "wb") as f:
        pickle.dump(model, f)
    logger.info(f"Saved {model_type} model to {local_path}")

    # Save to S3
    if HAS_BOTO3:
        try:
            s3 = boto3.client("s3")
            buf = BytesIO()
            pickle.dump(model, buf)
            buf.seek(0)
            s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=buf.read())
            logger.info(f"Saved {model_type} model to s3://{S3_BUCKET}/{s3_key}")
        except Exception as e:
            logger.warning(f"Failed to save to S3: {e}")


# ---------------------------------------------------------------------------
# Point-in-time feature backfill (training data builder)
# ---------------------------------------------------------------------------
#
# Each row of training data needs the SAME features the inference path
# (build_game_features) constructs, but computed *as of the day before the
# game* — no lookahead. We do this by:
#   1. Fetching each (pitcher, season) and (team, season) game log ONCE,
#      cached in a sqlite db on disk so repeat training runs are cheap.
#   2. For each historical game on date D, aggregating the cached game logs
#      where game_date < D to derive ERA/K9/WHIP/OPS/RG/RAG.
#
# Features we currently leave at neutral defaults (with rationale):
#   - temperature, wind_speed, weather_run_adj: historical hourly weather
#     by venue is genuinely expensive to backfill; out of scope for now.
#   - home_ttop_adj, away_ttop_adj: needs play-by-play data; deferred.
#   - umpire_run_adj: requires retrosheet umpire assignments; deferred.
#   - home/away_travel_adj: requires schedule + venue coords; deferred.
#   - home/away_pitcher_quality (Stuff+): requires Statcast pitch data;
#     deferred.
#   - injury_impact_*: no historical injury timeline backfill; deferred.
#   - home_field, ttop, umpire, travel, pitcher_quality: see DEFERRED_FEATURE_COLS
#     (still populated in rows / build_game_features for heuristics, not in FEATURE_COLS).
#
# The 6 pitcher stats + 6 team stats + park_factor + rest_differential
# (from team game-log cache) now carry REAL variation across rows.


def _cache_conn():
    """Open (and lazily initialize) the training-features sqlite cache."""
    conn = sqlite3.connect(TRAINING_CACHE_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pitcher_game_log (
            pitcher_id INTEGER, season INTEGER, game_date TEXT,
            ip REAL, er INTEGER, k INTEGER, bb INTEGER, h INTEGER,
            PRIMARY KEY (pitcher_id, season, game_date)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pitcher_log_fetched (
            pitcher_id INTEGER, season INTEGER, fetched_at TEXT,
            PRIMARY KEY (pitcher_id, season)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_game_log (
            team_id INTEGER, season INTEGER, game_date TEXT,
            runs_scored INTEGER, runs_allowed INTEGER,
            hits INTEGER, at_bats INTEGER, ops REAL,
            PRIMARY KEY (team_id, season, game_date)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_log_fetched (
            team_id INTEGER, season INTEGER, fetched_at TEXT,
            PRIMARY KEY (team_id, season)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pitcher_name_id (
            name TEXT PRIMARY KEY,
            pitcher_id INTEGER NOT NULL
        )"""
    )
    htb.init_backfill_tables(conn)
    return conn


def _resolve_pitcher_id(conn, name):
    """Map probable-starter name from schedule to MLBAM player id (cached)."""
    if not name:
        return None
    name = str(name).strip()
    if not name:
        return None

    row = conn.execute(
        "SELECT pitcher_id FROM pitcher_name_id WHERE name=?", (name,)
    ).fetchone()
    if row:
        return row[0]

    try:
        matches = mlbstatsapi.lookup_player(name)
        if not matches:
            logger.debug(f"No lookup match for pitcher {name!r}")
            return None
        pitcher_id = matches[0]["id"]
        conn.execute(
            "INSERT OR REPLACE INTO pitcher_name_id VALUES (?, ?)",
            (name, pitcher_id),
        )
        conn.commit()
        return pitcher_id
    except Exception as e:
        logger.debug(f"pitcher lookup failed for {name!r}: {e}")
        return None


def _game_starter_ids(conn, game):
    """Resolve home/away starter ids from schedule probable-pitcher names."""
    home_pid = _resolve_pitcher_id(conn, game.get("home_probable_pitcher"))
    away_pid = _resolve_pitcher_id(conn, game.get("away_probable_pitcher"))
    return home_pid, away_pid


def _fetch_pitcher_game_log(conn, pitcher_id, season):
    """Fetch & cache a pitcher's game log for a season."""
    if not pitcher_id:
        return
    row = conn.execute(
        "SELECT 1 FROM pitcher_log_fetched WHERE pitcher_id=? AND season=?",
        (pitcher_id, season),
    ).fetchone()
    if row:
        return

    try:
        url = (
            f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}"
            f"?hydrate=stats(group=[pitching],type=[gameLog],season={season})"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        people = resp.json().get("people") or []
        splits = []
        if people:
            for stat in people[0].get("stats") or []:
                if (
                    stat.get("type", {}).get("displayName") == "gameLog"
                    and stat.get("group", {}).get("displayName") == "pitching"
                ):
                    splits = stat.get("splits") or []
                    break

        rows = []
        for s in splits:
            d = (s.get("date") or s.get("gameDate") or "")[:10]
            if not d:
                continue
            st = s.get("stat", {})
            rows.append(
                (
                    pitcher_id,
                    season,
                    d,
                    float(st.get("inningsPitched", "0") or 0),
                    int(float(st.get("earnedRuns", 0) or 0)),
                    int(float(st.get("strikeOuts", 0) or 0)),
                    int(float(st.get("baseOnBalls", 0) or 0)),
                    int(float(st.get("hits", 0) or 0)),
                )
            )
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO pitcher_game_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except Exception as e:
        logger.debug(f"pitcher {pitcher_id} season {season} game log fetch failed: {e}")
        return

    conn.execute(
        "INSERT OR REPLACE INTO pitcher_log_fetched VALUES (?, ?, ?)",
        (pitcher_id, season, datetime.utcnow().isoformat()),
    )
    conn.commit()


def _pitcher_stats_as_of(conn, pitcher_id, season, as_of_date):
    """Aggregate cached game-log rows where game_date < as_of_date.

    Falls back to prior-season totals if this season has <10 IP as of the
    target date (mirrors get_pitcher_stats blending logic).
    """
    defaults = {"era": 4.50, "k9": 8.0, "whip": 1.35}
    if not pitcher_id:
        return defaults

    def _agg(pid, yr, cutoff):
        rows = conn.execute(
            """SELECT SUM(ip), SUM(er), SUM(k), SUM(bb), SUM(h)
               FROM pitcher_game_log
               WHERE pitcher_id=? AND season=? AND game_date<?""",
            (pid, yr, cutoff),
        ).fetchone()
        if not rows or rows[0] is None or rows[0] < 1:
            return None
        ip, er, k, bb, h = rows
        era = round((er * 9.0) / ip, 2)
        k9 = round((k / ip) * 9.0, 2)
        whip = round((bb + h) / ip, 3)
        return {"era": era, "k9": k9, "whip": whip, "ip": ip}

    cur = _agg(pitcher_id, season, as_of_date)
    if cur and cur["ip"] >= 10:
        return {"era": cur["era"], "k9": cur["k9"], "whip": cur["whip"]}

    # Backfill from prior season totals
    _fetch_pitcher_game_log(conn, pitcher_id, season - 1)
    prev = _agg(pitcher_id, season - 1, f"{season}-01-01")
    if prev and prev["ip"] >= 20:
        if cur and cur["ip"] >= 1:
            w = min(cur["ip"] / 20.0, 0.5)
            return {
                "era": round(w * cur["era"] + (1 - w) * prev["era"], 2),
                "k9": round(w * cur["k9"] + (1 - w) * prev["k9"], 2),
                "whip": round(w * cur["whip"] + (1 - w) * prev["whip"], 3),
            }
        return {"era": prev["era"], "k9": prev["k9"], "whip": prev["whip"]}

    return defaults


def _fetch_team_game_log(conn, team_id, season):
    """Fetch & cache a team's game-by-game runs scored/allowed for a season."""
    if not team_id:
        return
    row = conn.execute(
        "SELECT 1 FROM team_log_fetched WHERE team_id=? AND season=?", (team_id, season)
    ).fetchone()
    if row:
        return

    try:
        # Hitting log: runs scored, hits, AB, OPS
        url_h = (
            f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?"
            f"season={season}&group=hitting&stats=gameLog"
        )
        h_resp = requests.get(url_h, timeout=10).json()
        h_splits = (
            (h_resp.get("stats") or [{}])[0].get("splits", [])
            if h_resp.get("stats")
            else []
        )

        # Pitching log: runs allowed
        url_p = (
            f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?"
            f"season={season}&group=pitching&stats=gameLog"
        )
        p_resp = requests.get(url_p, timeout=10).json()
        p_splits = (
            (p_resp.get("stats") or [{}])[0].get("splits", [])
            if p_resp.get("stats")
            else []
        )

        ra_by_date = {}
        for s in p_splits:
            d = (s.get("date") or "")[:10]
            if d:
                ra_by_date[d] = int(float(s.get("stat", {}).get("runs", 0) or 0))

        rows = []
        for s in h_splits:
            d = (s.get("date") or "")[:10]
            if not d:
                continue
            st = s.get("stat", {})
            rs = int(float(st.get("runs", 0) or 0))
            hits = int(float(st.get("hits", 0) or 0))
            ab = int(float(st.get("atBats", 0) or 0))
            ops = float(st.get("ops", 0.720) or 0.720)
            rows.append((team_id, season, d, rs, ra_by_date.get(d, 0), hits, ab, ops))

        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO team_game_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except Exception as e:
        logger.debug(f"team {team_id} season {season} game log fetch failed: {e}")

    conn.execute(
        "INSERT OR REPLACE INTO team_log_fetched VALUES (?, ?, ?)",
        (team_id, season, datetime.utcnow().isoformat()),
    )
    conn.commit()


def _team_stats_as_of(conn, team_id, season, as_of_date):
    """Aggregate cached team game-log rows where game_date < as_of_date."""
    defaults = {"ops": 0.720, "runs_per_game": 4.5, "runs_allowed_per_game": 4.5}
    if not team_id:
        return defaults

    rows = conn.execute(
        """SELECT COUNT(*), SUM(runs_scored), SUM(runs_allowed),
                  AVG(ops)
           FROM team_game_log
           WHERE team_id=? AND season=? AND game_date<?""",
        (team_id, season, as_of_date),
    ).fetchone()

    if not rows or not rows[0] or rows[0] < 10:
        # Fall back to prior season totals
        _fetch_team_game_log(conn, team_id, season - 1)
        prev = conn.execute(
            """SELECT COUNT(*), SUM(runs_scored), SUM(runs_allowed), AVG(ops)
               FROM team_game_log WHERE team_id=? AND season=?""",
            (team_id, season - 1),
        ).fetchone()
        if prev and prev[0] and prev[0] >= 50:
            n, rs, ra, ops = prev
            return {
                "ops": round(ops, 3),
                "runs_per_game": round(rs / n, 2),
                "runs_allowed_per_game": round(ra / n, 2),
            }
        return defaults

    n, rs, ra, ops = rows
    return {
        "ops": round(ops, 3),
        "runs_per_game": round(rs / n, 2),
        "runs_allowed_per_game": round(ra / n, 2),
    }


def _team_days_rest_as_of(conn, team_id, season, as_of_date):
    """Calendar days since the team's last game strictly before ``as_of_date``."""
    if not team_id or not as_of_date:
        return 3
    row = conn.execute(
        """SELECT MAX(game_date) FROM team_game_log
           WHERE team_id=? AND game_date<?""",
        (team_id, as_of_date),
    ).fetchone()
    if not row or not row[0]:
        _fetch_team_game_log(conn, team_id, season - 1)
        row = conn.execute(
            """SELECT MAX(game_date) FROM team_game_log
               WHERE team_id=? AND game_date<?""",
            (team_id, as_of_date),
        ).fetchone()
    if not row or not row[0]:
        return 3
    last = date.fromisoformat(str(row[0])[:10])
    current = date.fromisoformat(str(as_of_date)[:10])
    return max((current - last).days, 1)


def tune_ensemble_weights(ensemble, val_df, target_col, classification=True):
    """Tune non-negative ensemble weights on a temporal validation slice.

    Minimizes Brier (win) or MAE (totals) subject to weights summing to 1.
    Stores previous weights under ``weights_default`` and diagnostics under
    ``weight_tuning``.
    """
    from scipy.optimize import minimize

    members = list(_iter_ensemble_models(ensemble))
    if not members or val_df is None or len(val_df) < 50:
        return ensemble

    X = val_df[FEATURE_COLS].fillna(0).values
    y = val_df[target_col].values.astype(float)
    cols = []
    names = []
    for name, model in members:
        try:
            if classification:
                cols.append(model.predict_proba(X)[:, 1])
            else:
                cols.append(model.predict(X).astype(float))
            names.append(name)
        except Exception as e:
            logger.debug(f"Skip {name} for weight tuning: {e}")
    if len(names) < 2:
        return ensemble

    P = np.column_stack(cols)
    default_weights = ensemble.get("weights", {})
    w0 = np.array(
        [float(default_weights.get(n, 1.0 / len(names))) for n in names], dtype=float
    )
    w0 = w0 / w0.sum()

    def _metric(w):
        w = np.asarray(w, dtype=float)
        w = w / max(w.sum(), 1e-9)
        pred = P @ w
        if classification:
            return brier_score_loss(y, np.clip(pred, 1e-6, 1 - 1e-6))
        return mean_absolute_error(y, pred)

    before = _metric(w0)
    n_m = len(names)
    bounds = [(0.0, 1.0)] * n_m
    constraints = {"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}
    result = minimize(
        _metric,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-8},
    )
    w_opt = result.x if result.success else w0
    w_opt = w_opt / max(w_opt.sum(), 1e-9)
    after = _metric(w_opt)

    tuned = dict(ensemble)
    tuned["weights_default"] = dict(default_weights)
    tuned["weights"] = {names[i]: float(w_opt[i]) for i in range(n_m)}
    tuned["weight_tuning"] = {
        "target": target_col,
        "classification": classification,
        "n_val": int(len(val_df)),
        "members": names,
        "metric_before": float(before),
        "metric_after": float(after),
        "optimizer_success": bool(result.success),
    }
    weight_str = ", ".join(f"{n}={tuned['weights'][n]:.2f}" for n in names)
    logger.info(
        f"Tuned {'win' if classification else 'total'} ensemble weights on "
        f"n={len(val_df)}: {before:.4f} → {after:.4f} ({weight_str})"
    )
    return tuned


def build_historical_training_data(
    seasons=None,
    quick=False,
    use_weather_api=True,
    accurate_bullpen=False,
):
    """Build training DataFrame with point-in-time feature backfill.

    For each historical game on date D, pitcher and team features are
    aggregated from cached game logs where game_date < D. Cached in
    `training_features_cache.db` for cheap repeat runs.

    Args:
        seasons: list of season years (default: last 2 completed seasons).
        quick: if True, only the last 200 final games from the most recent
               season — for smoke-testing the train pipeline.
        use_weather_api: fetch Open-Meteo archive weather (falls back to monthly avg).
        accurate_bullpen: use boxscore IP for bullpen fatigue (slow; default is schedule proxy).
    """
    if seasons is None:
        seasons = [CURRENT_SEASON - 2, CURRENT_SEASON - 1]
    if quick:
        seasons = seasons[-1:]  # most recent season only

    conn = _cache_conn()
    all_rows = []

    if not PARK_FACTOR_MAP:
        load_park_factors()

    for season in seasons:
        logger.info(f"Fetching {season} schedule...")
        try:
            schedule = mlbstatsapi.schedule(
                start_date=f"{season}-03-20", end_date=f"{season}-10-05"
            )
        except Exception as e:
            logger.error(f"Failed to fetch {season} schedule: {e}")
            continue

        finals = [
            g
            for g in schedule
            if g.get("status") in ("Final", "Game Over", "Completed Early")
            and g.get("home_score") is not None
            and g.get("away_score") is not None
        ]
        if quick:
            finals = finals[-200:]
        logger.info(f"Processing {len(finals)} final games for {season}")

        # Pre-warm pitcher and team caches in dependency order
        pitcher_names = set()
        for g in finals:
            if g.get("home_probable_pitcher"):
                pitcher_names.add(str(g["home_probable_pitcher"]).strip())
            if g.get("away_probable_pitcher"):
                pitcher_names.add(str(g["away_probable_pitcher"]).strip())
        team_ids = {g.get("home_id") for g in finals} | {
            g.get("away_id") for g in finals
        }

        pitcher_ids = set()
        for name in tqdm(pitcher_names, desc=f"pitcher lookup {season}"):
            pid = _resolve_pitcher_id(conn, name)
            if pid:
                pitcher_ids.add(pid)
        for pid in tqdm(pitcher_ids, desc=f"pitcher logs {season}"):
            _fetch_pitcher_game_log(conn, pid, season)
        for tid in tqdm(team_ids, desc=f"team logs {season}"):
            _fetch_team_game_log(conn, tid, season)

        venue_dates = {
            (g.get("venue_name") or "", game_date[:10])
            for g in finals
            if (game_date := (g.get("game_date") or "")[:10])
        }
        venue_dates = {(v, d) for v, d in venue_dates if v and d}
        for venue_name, gd in tqdm(
            sorted(venue_dates),
            desc=f"weather {season}",
        ):
            htb.get_weather_as_of(conn, venue_name, gd, use_api=use_weather_api)

        logger.info(
            f"[{season}] Backfilled pitcher/team stats, rest, weather, bullpen, injuries. "
            f"Still neutral: ttop, umpire, travel, pitcher_quality."
        )

        for game in finals:
            game_date = game.get("game_date", "")[:10]
            if not game_date:
                continue

            home_pid, away_pid = _game_starter_ids(conn, game)
            home_tid = game.get("home_id")
            away_tid = game.get("away_id")

            # Skip games where we cannot resolve either starter
            if not home_pid or not away_pid:
                continue

            home_p = _pitcher_stats_as_of(conn, home_pid, season, game_date)
            away_p = _pitcher_stats_as_of(conn, away_pid, season, game_date)
            home_t = _team_stats_as_of(conn, home_tid, season, game_date)
            away_t = _team_stats_as_of(conn, away_tid, season, game_date)

            venue = game.get("venue_name") or ""
            park_id = VENUE_PARK_ID_MAP.get(venue)
            base_park_factor = PARK_FACTOR_MAP.get(park_id, 1.0) if park_id else 1.0
            home_rest = _team_days_rest_as_of(conn, home_tid, season, game_date)
            away_rest = _team_days_rest_as_of(conn, away_tid, season, game_date)

            ctx = htb.enrich_context_features(
                conn,
                venue,
                game_date,
                home_tid,
                away_tid,
                season,
                base_park_factor,
                use_weather_api=use_weather_api,
                accurate_bullpen=accurate_bullpen,
            )

            home_score = int(game["home_score"])
            away_score = int(game["away_score"])

            all_rows.append(
                {
                    "game_id": game["game_id"],
                    "date": game_date,
                    "home_team": game.get("home_name", ""),
                    "away_team": game.get("away_name", ""),
                    "home_score": home_score,
                    "away_score": away_score,
                    "total_runs": home_score + away_score,
                    "home_win": 1 if home_score > away_score else 0,
                    # Backfilled point-in-time features
                    "home_starter_era": home_p["era"],
                    "away_starter_era": away_p["era"],
                    "home_starter_k9": home_p["k9"],
                    "away_starter_k9": away_p["k9"],
                    "home_starter_whip": home_p["whip"],
                    "away_starter_whip": away_p["whip"],
                    "home_lineup_ops": home_t["ops"],
                    "away_lineup_ops": away_t["ops"],
                    "home_recent_runs_avg": home_t["runs_per_game"],
                    "away_recent_runs_avg": away_t["runs_per_game"],
                    "home_recent_runs_allowed_avg": home_t["runs_allowed_per_game"],
                    "away_recent_runs_allowed_avg": away_t["runs_allowed_per_game"],
                    "park_factor": ctx["park_factor"],
                    "home_bullpen_fatigue": ctx["home_bullpen_fatigue"],
                    "away_bullpen_fatigue": ctx["away_bullpen_fatigue"],
                    "temperature": ctx["temperature"],
                    "wind_speed": ctx["wind_speed"],
                    "rest_differential": float(home_rest - away_rest),
                    "home_field": 1.0,
                    "injury_impact_home": ctx["injury_impact_home"],
                    "injury_impact_away": ctx["injury_impact_away"],
                    "weather_run_adj": ctx["weather_run_adj"],
                    "home_ttop_adj": 0.0,
                    "away_ttop_adj": 0.0,
                    "umpire_run_adj": 0.0,
                    "home_travel_adj": 0.0,
                    "away_travel_adj": 0.0,
                    "home_pitcher_quality": 50.0,
                    "away_pitcher_quality": 50.0,
                }
            )

    conn.close()
    df = pd.DataFrame(all_rows)
    logger.info(f"Built training data: {len(df)} games across {seasons}")
    return df


def train_game_models(df, fast=False, tune_weights=False, val_fraction=0.15):
    """Train diverse ensemble of win probability and run total models.

    Technical Playbook §7: Current XGB+GBM+LGBM ensemble is too homogeneous.
    Adds RandomForest, CatBoost, and LogisticRegression/ElasticNet for diversity.
    Uses NNLS-style meta-learner (simple average for initial implementation).

    Uses TimeSeriesSplit CV for temporal validation when ``fast`` is False.

    Args:
        df: Training rows including FEATURE_COLS, home_win, total_runs, date.
        fast: If True, skip hyperparameter search (for walk-forward evaluation).
        tune_weights: If True, reweight ensemble members on the last ``val_fraction``
            of training rows (temporal) to minimize Brier / MAE.
        val_fraction: Tail fraction of ``df`` used only for weight tuning.
    """
    df = df.sort_values("date").reset_index(drop=True)
    val_df = None
    if tune_weights and len(df) >= 200:
        split_at = max(int(len(df) * (1.0 - val_fraction)), len(df) - 50)
        val_df = df.iloc[split_at:].copy()

    X = df[FEATURE_COLS].fillna(0).values
    y_win = df["home_win"].values
    y_total = df["total_runs"].values

    tscv = TimeSeriesSplit(n_splits=5)

    # --- Win Probability Ensemble ---
    logger.info("Training diverse win probability ensemble...")

    # Model 1: XGBoost (primary)
    win_params = {
        "clf__n_estimators": [100, 200, 300],
        "clf__max_depth": [3, 4, 5, 6],
        "clf__learning_rate": [0.05, 0.1, 0.15],
        "clf__subsample": [0.7, 0.8, 0.9],
        "clf__colsample_bytree": [0.7, 0.8, 0.9],
    }

    win_pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                XGBClassifier(
                    eval_metric="logloss",
                    random_state=42,
                ),
            ),
        ]
    )

    if fast:
        win_pipeline.set_params(
            **{f"clf__{k}": v for k, v in FAST_XGB_WIN_PARAMS.items()}
        )
        win_pipeline.fit(X, y_win)
        xgb_win = win_pipeline
        logger.info(
            f"XGBoost win (fast) in-sample Brier: "
            f"{brier_score_loss(y_win, xgb_win.predict_proba(X)[:, 1]):.4f}"
        )
    else:
        win_search = RandomizedSearchCV(
            win_pipeline,
            win_params,
            n_iter=20,
            cv=tscv,
            scoring="neg_brier_score",
            random_state=42,
            n_jobs=-1,
        )
        win_search.fit(X, y_win)
        xgb_win = win_search.best_estimator_
        logger.info(f"XGBoost win Brier: {-win_search.best_score_:.4f}")

    # Model 2: RandomForest (uncorrelated errors)
    logger.info("Training RandomForest win model...")
    rf_win = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=200, max_depth=6, random_state=42, n_jobs=-1
                ),
            ),
        ]
    )
    rf_win.fit(X, y_win)

    # Model 3: Logistic Regression (simple, well-calibrated baseline)
    logger.info("Training LogisticRegression win model...")
    lr_win = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=1.0, max_iter=500, random_state=42)),
        ]
    )
    lr_win.fit(X, y_win)

    # Model 4: CatBoost (if available)
    cb_win = None
    if HAS_CATBOOST:
        logger.info("Training CatBoost win model...")
        cb_win = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    CatBoostClassifier(
                        iterations=200,
                        depth=5,
                        learning_rate=0.1,
                        random_seed=42,
                        verbose=0,
                    ),
                ),
            ]
        )
        cb_win.fit(X, y_win)

    # Package ensemble
    win_ensemble = {
        "xgboost": xgb_win,
        "random_forest": rf_win,
        "logistic_regression": lr_win,
        "catboost": cb_win,
        # Ensemble weights (can be tuned via NNLS meta-learner later)
        "weights": {
            "xgboost": 0.40,
            "random_forest": 0.25,
            "logistic_regression": 0.15,
            "catboost": 0.20,
        },
    }

    # --- Run Total Ensemble ---
    logger.info("Training diverse run total ensemble...")

    # Model 1: XGBoost
    total_params = {
        "reg__n_estimators": [100, 200, 300],
        "reg__max_depth": [3, 4, 5, 6],
        "reg__learning_rate": [0.05, 0.1, 0.15],
        "reg__subsample": [0.7, 0.8, 0.9],
    }

    total_pipeline = Pipeline(
        [("scaler", StandardScaler()), ("reg", XGBRegressor(random_state=42))]
    )

    if fast:
        total_pipeline.set_params(
            **{f"reg__{k}": v for k, v in FAST_XGB_TOTAL_PARAMS.items()}
        )
        total_pipeline.fit(X, y_total)
        xgb_total = total_pipeline
        logger.info(
            f"XGBoost total (fast) in-sample MAE: "
            f"{mean_absolute_error(y_total, xgb_total.predict(X)):.2f}"
        )
    else:
        total_search = RandomizedSearchCV(
            total_pipeline,
            total_params,
            n_iter=20,
            cv=tscv,
            scoring="neg_mean_absolute_error",
            random_state=42,
            n_jobs=-1,
        )
        total_search.fit(X, y_total)
        xgb_total = total_search.best_estimator_
        logger.info(f"XGBoost total MAE: {-total_search.best_score_:.2f}")

    # Model 2: RandomForest
    logger.info("Training RandomForest total model...")
    rf_total = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "reg",
                RandomForestRegressor(
                    n_estimators=200, max_depth=6, random_state=42, n_jobs=-1
                ),
            ),
        ]
    )
    rf_total.fit(X, y_total)

    # Model 3: ElasticNet (linear, regularized)
    logger.info("Training ElasticNet total model...")
    en_total = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("reg", ElasticNet(alpha=0.1, l1_ratio=0.5, random_state=42)),
        ]
    )
    en_total.fit(X, y_total)

    # Model 4: CatBoost (if available)
    cb_total = None
    if HAS_CATBOOST:
        logger.info("Training CatBoost total model...")
        cb_total = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "reg",
                    CatBoostRegressor(
                        iterations=200,
                        depth=5,
                        learning_rate=0.1,
                        random_seed=42,
                        verbose=0,
                    ),
                ),
            ]
        )
        cb_total.fit(X, y_total)

    total_ensemble = {
        "xgboost": xgb_total,
        "random_forest": rf_total,
        "elastic_net": en_total,
        "catboost": cb_total,
        "weights": {
            "xgboost": 0.40,
            "random_forest": 0.25,
            "elastic_net": 0.15,
            "catboost": 0.20,
        },
    }

    if val_df is not None:
        win_ensemble = tune_ensemble_weights(
            win_ensemble,
            val_df,
            "home_win",
            classification=True,
        )
        total_ensemble = tune_ensemble_weights(
            total_ensemble,
            val_df,
            "total_runs",
            classification=False,
        )

    return win_ensemble, total_ensemble


def fit_and_save_win_calibrator(
    train_df: pd.DataFrame,
    val_fraction: float = 0.15,
    min_cal_rows: int = 50,
    min_train_core_rows: int = 400,
    method: str = "auto",
    calibration_fast: bool = True,
    tune_weights: bool = False,
) -> None:
    """Fit isotonic/Platt on OOS tail preds (split_train protocol used in eval).

    Trains a shadow win ensemble on the temporal core (~85%% of rows), predicts
    only the held-out cal tail (~15%%), then fits the calibrator on those OOS
    probabilities. The production ``game_model_win.pkl`` (trained on all rows)
    stays unchanged; only the calibrator pickle is written.

    ``calibration_fast=True`` (default) mirrors ``game_model_eval`` fast training.
    """
    from app.services.etl.mlb.win_probability_calibration import (
        WinProbabilityCalibrator,
        save_win_calibrator,
        split_calibration_holdout,
    )

    train_df = train_df.sort_values("date").reset_index(drop=True)
    train_core, cal_df = split_calibration_holdout(
        train_df,
        val_fraction,
        min_cal_rows,
    )
    if len(train_core) < min_train_core_rows or len(cal_df) < min_cal_rows:
        logger.warning(
            "Win calibrator not saved — insufficient rows for OOS split "
            "(core=%s, cal=%s)",
            len(train_core),
            len(cal_df),
        )
        return

    logger.info(
        "Fitting win calibrator (OOS tail): core n=%s (%s → %s), cal n=%s",
        len(train_core),
        train_core["date"].min(),
        train_core["date"].max(),
        len(cal_df),
    )
    cal_win_ensemble, _ = train_game_models(
        train_core,
        fast=calibration_fast,
        tune_weights=tune_weights,
    )
    X_cal = cal_df[FEATURE_COLS].fillna(0).values
    p_cal_oos = ensemble_predict_proba_batch(cal_win_ensemble, X_cal)
    y_cal = cal_df["home_win"].values.astype(int)

    bundle = WinProbabilityCalibrator()
    bundle.train_mode = "split_train_oos_tail"
    bundle.fit(p_cal_oos, y_cal, method=method)

    save_win_calibrator(bundle, WIN_CALIBRATOR_LOCAL)
    if HAS_BOTO3:
        try:
            s3 = boto3.client("s3")
            buf = BytesIO()
            pickle.dump(bundle.to_dict(), buf)
            buf.seek(0)
            s3.put_object(Bucket=S3_BUCKET, Key=WIN_CALIBRATOR_S3_KEY, Body=buf.read())
            logger.info(
                "Saved win calibrator to s3://%s/%s", S3_BUCKET, WIN_CALIBRATOR_S3_KEY
            )
        except Exception as exc:
            logger.warning("S3 win calibrator upload failed: %s", exc)


def load_win_calibrator_for_production():
    """Load game-model win calibrator (local, then S3)."""
    from app.services.etl.mlb.win_probability_calibration import (
        WinProbabilityCalibrator,
        load_win_calibrator,
    )

    cal = load_win_calibrator(WIN_CALIBRATOR_LOCAL)
    if cal is not None:
        return cal
    if HAS_BOTO3:
        try:
            s3 = boto3.client("s3")
            obj = s3.get_object(Bucket=S3_BUCKET, Key=WIN_CALIBRATOR_S3_KEY)
            data = pickle.load(BytesIO(obj["Body"].read()))
            cal = WinProbabilityCalibrator.from_dict(data)
            if cal.is_fitted:
                return cal
        except Exception:
            pass
    return None


def ensemble_with_weights(ensemble, weights):
    """Shallow copy of ensemble using alternate member weights."""
    alt = dict(ensemble)
    alt["weights"] = dict(weights)
    return alt


def ensemble_predict_proba(ensemble, X):
    """Generate ensemble prediction by weighted averaging constituent models.

    Technical Playbook §7: Meta-learner should be simple (NNLS/weighted average).
    """
    weights = ensemble.get("weights", {})
    total_weight = 0.0
    weighted_prob = 0.0

    for name, model in _iter_ensemble_models(ensemble):
        w = weights.get(name, 0.25)
        try:
            prob = float(model.predict_proba(X)[0][1])
            weighted_prob += w * prob
            total_weight += w
        except Exception:
            continue

    if total_weight > 0:
        return weighted_prob / total_weight
    return 0.5


def ensemble_predict_value(ensemble, X):
    """Generate ensemble regression prediction by weighted averaging."""
    weights = ensemble.get("weights", {})
    total_weight = 0.0
    weighted_val = 0.0

    for name, model in _iter_ensemble_models(ensemble):
        w = weights.get(name, 0.25)
        try:
            val = float(model.predict(X)[0])
            weighted_val += w * val
            total_weight += w
        except Exception:
            continue

    if total_weight > 0:
        return weighted_val / total_weight
    return 9.0


def ensemble_predict_proba_batch(ensemble, X):
    """Vectorized ensemble home-win probability for 2D feature matrix ``X``."""
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    n = X.shape[0]
    weights = ensemble.get("weights", {})
    acc = np.zeros(n, dtype=float)
    tw = np.zeros(n, dtype=float)
    for name, model in _iter_ensemble_models(ensemble):
        w = float(weights.get(name, 0.25))
        try:
            p = model.predict_proba(X)[:, 1]
            acc += w * p
            tw += w
        except Exception:
            continue
    out = acc / np.maximum(tw, 1e-9)
    return np.clip(out, 1e-6, 1.0 - 1e-6)


def ensemble_predict_value_batch(ensemble, X):
    """Vectorized ensemble projected total runs for 2D feature matrix ``X``."""
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    n = X.shape[0]
    weights = ensemble.get("weights", {})
    acc = np.zeros(n, dtype=float)
    tw = np.zeros(n, dtype=float)
    for name, model in _iter_ensemble_models(ensemble):
        w = float(weights.get(name, 0.25))
        try:
            v = model.predict(X).astype(float)
            acc += w * v
            tw += w
        except Exception:
            continue
    out = acc / np.maximum(tw, 1e-9)
    return out


def predict_games(games):
    """Generate predictions for a list of games.

    Uses trained ensemble models if available, falls back to heuristic.

    Returns list of prediction dicts.
    """
    win_model = load_model("win")
    total_model = load_model("total")

    # Check if model is an ensemble dict or a single model
    use_ensemble = isinstance(win_model, dict) and "weights" in win_model
    use_ml = win_model is not None and total_model is not None

    if use_ml:
        logger.info(
            f"Using {'ensemble' if use_ensemble else 'single'} ML models for predictions"
        )
    else:
        logger.info("No trained models found, using heuristic predictions")

    win_calibrator = load_win_calibrator_for_production()
    venn_calibrator = None
    if win_calibrator is None:
        try:
            from app.services.etl.mlb.venn_abers import VennAbersCalibrator

            venn_calibrator = VennAbersCalibrator.load()
            if not venn_calibrator.is_fitted:
                venn_calibrator = None
        except Exception:
            venn_calibrator = None
    if win_calibrator is not None:
        logger.info(
            "Using win isotonic/platt calibrator (%s, n=%s)",
            win_calibrator.method,
            win_calibrator.n_samples,
        )
    elif venn_calibrator is not None:
        logger.info("Using Venn-Abers calibrator (no game_model_win_calibrator.pkl)")

    predictions = []

    for game in games:
        features = build_game_features(game)
        if features is None:
            logger.warning(f"Skipping game {game.get('game_id')} — missing features")
            continue

        if use_ml:
            X = np.array([[features[col] for col in FEATURE_COLS]])
            if use_ensemble:
                home_win_prob = ensemble_predict_proba(win_model, X)
                projected_total = ensemble_predict_value(total_model, X)
            else:
                home_win_prob = float(win_model.predict_proba(X)[0][1])
                projected_total = float(total_model.predict(X)[0])
            raw_home_win_prob = home_win_prob
        else:
            home_win_prob = predict_win_probability_heuristic(features)
            projected_total = predict_total_runs_heuristic(features)
            raw_home_win_prob = home_win_prob

        if use_ml and win_calibrator is not None:
            home_win_prob = win_calibrator.predict_single(raw_home_win_prob)
        elif use_ml and venn_calibrator is not None:
            home_win_prob = venn_calibrator.predict_single(raw_home_win_prob)
        else:
            home_win_prob = raw_home_win_prob

        away_win_prob = round(1.0 - home_win_prob, 4)
        home_runs = round(
            projected_total * home_win_prob / max(home_win_prob + away_win_prob, 0.01),
            1,
        )
        away_runs = round(projected_total - home_runs, 1)
        run_line = round(home_runs - away_runs, 1)

        predictions.append(
            {
                "game_id": game["game_id"],
                "home_team": game.get("home_name", ""),
                "away_team": game.get("away_name", ""),
                "home_team_id": game.get("home_id"),
                "away_team_id": game.get("away_id"),
                "home_pitcher_id": str(game.get("home_pitcher_id", "")),
                "home_pitcher_name": game.get("home_probable_pitcher", ""),
                "away_pitcher_id": str(game.get("away_pitcher_id", "")),
                "away_pitcher_name": game.get("away_probable_pitcher", ""),
                "venue_name": game.get("venue_name", ""),
                "game_time": game.get("game_datetime"),
                "home_win_prob": round(home_win_prob, 4),
                "home_win_prob_raw": round(raw_home_win_prob, 4),
                "away_win_prob": round(away_win_prob, 4),
                "projected_total": round(projected_total, 1),
                "home_projected_runs": home_runs,
                "away_projected_runs": away_runs,
                "run_line": run_line,
                "xgb_win_prob": round(raw_home_win_prob, 4),
                # Feature snapshot
                "home_bullpen_fatigue": features["home_bullpen_fatigue"],
                "away_bullpen_fatigue": features["away_bullpen_fatigue"],
                "park_factor": features["park_factor"],
                "temperature": features["temperature"],
                "wind_speed": features["wind_speed"],
            }
        )

    return predictions


def get_todays_games():
    """Fetch today's scheduled games with probable pitchers and venue info."""
    today_str = date.today().strftime("%Y-%m-%d")
    schedule = mlbstatsapi.schedule(date=today_str)
    games = []
    conn = _cache_conn()

    try:
        for g in schedule:
            # Get venue name
            venue_name = ""
            try:
                game_data = mlbstatsapi.get("game", {"gamePk": g["game_id"]})
                venue_name = (
                    game_data.get("gameData", {}).get("venue", {}).get("name", "")
                )
            except Exception:
                pass

            home_pid, away_pid = _game_starter_ids(conn, g)
            games.append(
                {
                    "game_id": g["game_id"],
                    "home_name": g["home_name"],
                    "away_name": g["away_name"],
                    "home_id": g["home_id"],
                    "away_id": g["away_id"],
                    "home_pitcher_id": home_pid,
                    "away_pitcher_id": away_pid,
                    "home_probable_pitcher": g.get("home_probable_pitcher", ""),
                    "away_probable_pitcher": g.get("away_probable_pitcher", ""),
                    "venue_name": venue_name,
                    "game_datetime": g.get("game_datetime"),
                }
            )
    finally:
        conn.close()

    return games


def main():
    parser = argparse.ArgumentParser(description="MLB Game-Level Model")
    parser.add_argument(
        "--train", action="store_true", help="Train models on historical data"
    )
    parser.add_argument(
        "--predict", action="store_true", help="Generate predictions for today"
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=None,
        help="Seasons to use for training (e.g., 2023 2024 2025)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Smoke-test training on ~200 games from the latest season",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run seasonal holdout evaluation (writes JSON under scripts/mlb/backtest_results/)",
    )
    parser.add_argument(
        "--full-train",
        action="store_true",
        help="With --evaluate: use full hyperparameter search per fold (very slow)",
    )
    parser.add_argument(
        "--tune-weights",
        action="store_true",
        help="With --train: tune ensemble weights on last 15%% of training rows",
    )
    parser.add_argument(
        "--no-tune-weights",
        action="store_true",
        help="With --evaluate: keep fixed ensemble weights",
    )
    parser.add_argument(
        "--no-weather-api",
        action="store_true",
        help="With --train: use monthly weather estimates instead of Open-Meteo",
    )
    parser.add_argument(
        "--accurate-bullpen",
        action="store_true",
        help="With --train: boxscore-based bullpen fatigue (much slower)",
    )
    parser.add_argument(
        "--cal-train-full",
        action="store_true",
        help="With --evaluate: train on full season, calibrate on tail only",
    )
    parser.add_argument(
        "--compare-cal-train-modes",
        action="store_true",
        help="With --evaluate: compare split_train vs full_train_tail_cal",
    )
    args = parser.parse_args()

    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        load_park_factors()

        if args.train:
            df = build_historical_training_data(
                args.seasons,
                quick=args.quick,
                use_weather_api=not args.no_weather_api,
                accurate_bullpen=args.accurate_bullpen,
            )
            cov = feature_coverage_report(df)
            logger.info(
                "Feature coverage (pct still at neutral default): %s",
                {
                    r["feature"]: r["pct_at_neutral_default"]
                    for r in cov["features"]
                    if r["pct_at_neutral_default"] is not None
                    and r["pct_at_neutral_default"] > 0
                },
            )
            if len(df) < 100:
                logger.error("Not enough training data. Need at least 100 games.")
                return
            win_ensemble, total_ensemble = train_game_models(
                df,
                tune_weights=args.tune_weights,
            )
            save_model(win_ensemble, "win")
            save_model(total_ensemble, "total")
            fit_and_save_win_calibrator(
                df,
                tune_weights=args.tune_weights,
                calibration_fast=True,
            )
            logger.info(
                f"Training complete. Ensemble models saved "
                f"(win: {len([k for k,v in win_ensemble.items() if k != 'weights' and v])} models, "
                f"total: {len([k for k,v in total_ensemble.items() if k != 'weights' and v])} models)"
            )

        elif args.evaluate:
            from app.services.etl.mlb import game_model_eval as gme

            seasons = (
                args.seasons
                if args.seasons
                else [CURRENT_SEASON - 2, CURRENT_SEASON - 1]
            )
            if len(set(seasons)) < 2:
                logger.error(
                    "--evaluate needs at least two distinct years in --seasons"
                )
                return
            gme.run_seasonal_holdout(
                sorted(set(seasons)),
                fast_train=not args.full_train,
                tune_weights=not args.no_tune_weights,
                cal_train_modes=(
                    [gme.CAL_TRAIN_SPLIT, gme.CAL_TRAIN_FULL]
                    if args.compare_cal_train_modes
                    else (
                        [gme.CAL_TRAIN_FULL]
                        if args.cal_train_full
                        else [gme.CAL_TRAIN_SPLIT]
                    )
                ),
            )

        elif args.predict:
            games = get_todays_games()
            if not games:
                logger.info("No games scheduled today.")
                return
            predictions = predict_games(games)
            for pred in predictions:
                logger.info(
                    f"{pred['away_team']} @ {pred['home_team']}: "
                    f"WP={pred['home_win_prob']:.1%} | "
                    f"Total={pred['projected_total']} | "
                    f"Line={pred['run_line']:+.1f}"
                )
        else:
            parser.print_help()
    finally:
        close_session()


if __name__ == "__main__":
    main()
