"""Player feature extraction for XGBoost stat-projection models (multi-stat).

Direct port of `_extract_features` from YetiBets/scripts/nba/ml_models/predict.py.
This is intentionally a separate code path from the rule-based
`PlayerFeatureCalculator` in YetiBets/scripts/nba/feature_engineering.py —
that one mixes columns the training pipeline never saw, and what matters for
model accuracy is *bit-for-bit reproducing the training feature vector*.

Each call to `build_features(...)` returns a dict keyed by the training-time
feature names for the requested stat. Features the model expects but we can't
compute (e.g. the un-prefixed `trend` and `trend_pct` — distinct from the
`<stat>_trend` / `<stat>_trend_pct` features, neither of which YetiBets's
predictor produced either) are simply absent from the dict; `_ml_predict.predict`
fills them with 0 when ordering the vector. That matches how the model was
trained.

Backward-compat wrapper `build_points_features(db, player_id, game_date,
opponent_team_id)` is preserved for existing imports — it calls into
`build_features(..., stat_col="points")`.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import and_, or_

from app.models.predictions_models import NBAGameLines, TeamDefenseStats
from app.services.etl.nba._espn import NBA_TEAM_NAMES
from app.services.etl.nba._samples import player_games
from app.services.etl.nba._team_defense import team_defense_as_of

logger = logging.getLogger(__name__)

# Cached training datasets are keyed by this; bump it when features change.
# v3: opponent defense as of each game's date, the Vegas line found through
# the opponent, and the rate / recency / volume features below.
FEATURES_VERSION = 3

# Half-lives (in games) of the exponentially weighted averages.
EWM_HALF_LIVES = (5, 10)
# Shot-volume and role columns averaged alongside the target stat.
VOLUME_WINDOWS: dict[str, tuple[int, ...]] = {
    "fg_attempts": (10, 20),
    "three_pt_attempts": (10,),
    "ft_attempts": (10,),
    "turnovers": (10,),
    "personal_fouls": (10,),
}

# Per-stat `opp_stat_allowed` column on TeamDefenseStats. Mapping is lifted
# verbatim from YetiBets/scripts/nba/ml_models/predict.py (see the
# stat_defense_map dict around line ~350). Note the quirks:
#   * `steals` uses `turnovers` (a team that forces turnovers also lets the
#     opposing star steal less, roughly).
#   * `blocks` uses the team's own `blocks` count as a proxy for the
#     shot-blocking environment.
# These are odd-looking but they're what the model was TRAINED on, so we have
# to reproduce them exactly or the model gets garbage at inference.
_OPP_STAT_ALLOWED_COL: dict[str, str] = {
    "points": "points_allowed_per_game",
    "rebounds": "rebounds_allowed_per_game",
    "assists": "assists_allowed_per_game",
    "three_pt_made": "three_pt_made_allowed_per_game",
    "free_throws_made": "free_throws_allowed_per_game",
    "steals": "turnovers",
    "blocks": "blocks",
}


def _games_to_df(games) -> pd.DataFrame:
    """Hydrate RecentGames ORM rows into the DataFrame shape the original
    feature extractor expected. Column names mirror the YetiBets source so
    the downstream pandas ops are identical."""
    return pd.DataFrame(
        [
            {
                "game_date": g.game_date,
                "opponent_team_id": g.opponent_team_id,
                "minutes": g.minutes,
                "points": g.points,
                "assists": g.assists,
                "rebounds": g.rebounds,
                "three_pt_made": g.three_pt_made,
                "blocks": g.blocks,
                "steals": g.steals,
                "free_throws_made": g.free_throws_made,
                "fg_attempts": g.fg_attempts,
                "three_pt_attempts": g.three_pt_attempts,
                "ft_attempts": g.ft_attempts,
                "turnovers": g.turnovers,
                "personal_fouls": g.personal_fouls,
                "usage_percentage": g.usage_percentage,
                "true_shooting_percentage": g.true_shooting_percentage,
                "effective_field_goal_percentage": g.effective_field_goal_percentage,
                "offensive_rating": g.offensive_rating,
                "defensive_rating": g.defensive_rating,
                "assist_percentage": g.assist_percentage,
                "rebound_percentage": g.rebound_percentage,
                "turnover_percentage": getattr(g, "turnover_percentage", None),
                "plus_minus": g.plus_minus,
                "pace": g.pace,
                "home_game": g.home_game,
            }
            for g in games
        ]
    )


def _mean(series: pd.Series) -> float:
    values = series.dropna()
    return float(values.mean()) if len(values) else 0.0


def _ewm(series: pd.Series, half_life: float) -> float:
    """Exponentially weighted mean of a newest-first series: a game
    ``half_life`` games back counts half as much as the latest one."""
    values = series.dropna().to_numpy(dtype=float)
    if not len(values):
        return 0.0
    weights = 0.5 ** (np.arange(len(values)) / half_life)
    return float((values * weights).sum() / weights.sum())


def _recency_rate_features(games_df: pd.DataFrame, stat_col: str) -> dict:
    """Recency-weighted, per-minute and volume features (newest game first)."""
    stat = games_df[stat_col]
    minutes = games_df["minutes"]
    out: dict = {}

    for half_life in EWM_HALF_LIVES:
        out[f"{stat_col}_ewm_{half_life}"] = _ewm(stat, half_life)
    out[f"{stat_col}_avg_season"] = _mean(stat)
    last = stat.dropna()
    out[f"{stat_col}_last"] = float(last.iloc[0]) if len(last) else 0.0
    out["sample_games"] = len(games_df)

    # Production per minute over the last 20, re-scaled by recent minutes: a
    # bench player handed a starter's minutes projects like one right away.
    recent = games_df.head(20)[[stat_col, "minutes"]].dropna()
    played = float(recent["minutes"].sum())
    per_minute = float(recent[stat_col].sum()) / played if played > 0 else 0.0
    out[f"{stat_col}_per_min_20"] = per_minute
    out[f"{stat_col}_rate_x_min_5"] = per_minute * _mean(minutes.head(5))
    out[f"{stat_col}_rate_x_min_10"] = per_minute * _mean(minutes.head(10))

    out["minutes_avg_3"] = _mean(minutes.head(3))
    out["minutes_avg_20"] = _mean(minutes.head(20))
    out["minutes_avg_season"] = _mean(minutes)
    out["minutes_ewm_3"] = _ewm(minutes, 3)
    played_minutes = minutes.dropna()
    out["minutes_last"] = float(played_minutes.iloc[0]) if len(played_minutes) else 0.0

    for col, windows in VOLUME_WINDOWS.items():
        for window in windows:
            out[f"{col}_avg_{window}"] = _mean(games_df.head(window)[col])
    return out


def _opponent_defense(db, opponent_team_id: int, game_date: date) -> dict:
    """Opponent's per-game allowed stats before ``game_date``; the stored
    current-day row only when the game log has nothing for that team."""
    defense = team_defense_as_of(db, opponent_team_id, game_date)
    if defense is not None:
        return defense
    row = db.query(TeamDefenseStats).filter_by(team_id=opponent_team_id).first()
    if row is None:
        return {}
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _game_line_vs(db, opponent_team_id: int, game_date: date):
    """(line row, player's team is home) for the game against the opponent on
    ``game_date``, or None when no line is stored."""
    opp_name = NBA_TEAM_NAMES.get(opponent_team_id)
    if not opp_name:
        return None
    line = (
        db.query(NBAGameLines)
        .filter(
            and_(
                NBAGameLines.game_date == game_date,
                or_(
                    NBAGameLines.home_team_name.ilike(f"%{opp_name}%"),
                    NBAGameLines.away_team_name.ilike(f"%{opp_name}%"),
                ),
            )
        )
        .first()
    )
    if line is None:
        return None
    opponent_is_home = opp_name.lower() in (line.home_team_name or "").lower()
    return line, not opponent_is_home


def build_features(
    db,
    player_id: int,
    game_date: date,
    opponent_team_id: int,
    stat_col: str,
) -> Optional[dict]:
    """Build a stat-specific feature vector for one player-vs-opponent matchup.

    Args:
        db: an open SessionLocal()
        player_id: NBA.com player_id
        game_date: target game date (features use only games BEFORE this,
            from this season once there are enough — see `_samples`)
        opponent_team_id: NBA.com opponent team_id
        stat_col: target stat key — one of the keys in _OPP_STAT_ALLOWED_COL

    Returns:
        A dict keyed by the training-time feature names, or None if the player
        has fewer than 5 games (insufficient data — caller should skip).
    """
    if stat_col not in _OPP_STAT_ALLOWED_COL:
        raise ValueError(
            f"Unknown stat_col {stat_col!r}; supported: "
            f"{sorted(_OPP_STAT_ALLOWED_COL)}"
        )

    historical_games = player_games(db, player_id, game_date, 50)
    if len(historical_games) < 5:
        return None

    games_df = _games_to_df(historical_games)

    features: dict = {}

    # ---- Rolling avg/std for the target stat (5/10/20 games) and minutes
    # (5/10). A window longer than the sample, early in the season, averages
    # the games there are: a 0 would read as a player who doesn't score.
    for col, windows in ((stat_col, (5, 10, 20)), ("minutes", (5, 10))):
        for window in windows:
            recent = games_df.head(window)[col].dropna()
            features[f"{col}_avg_{window}"] = recent.mean() if len(recent) else 0
            features[f"{col}_std_{window}"] = recent.std() if len(recent) > 1 else 0

    # ---- Recency, per-minute rate and volume (FEATURES_VERSION 3).
    # On a chronological holdout of 2024-25 through early 2026-27 these took
    # the points model from 4.69 to 4.63 MAE (rebounds 1.894 -> 1.871, assists
    # 1.368 -> 1.356): windowed means throw away how recent each game is, and
    # a player's production follows his minutes, which move faster than his
    # per-minute rate. Models trained before v3 ignore these columns.
    features.update(_recency_rate_features(games_df, stat_col))

    # ---- Trend: last 5 games vs the last 20 (or all of a shorter sample).
    if len(games_df) >= 10:
        recent_avg = games_df.head(5)[stat_col].dropna().mean()
        baseline_avg = games_df.head(20)[stat_col].dropna().mean()
        if baseline_avg and baseline_avg > 0:
            trend_pct = (recent_avg - baseline_avg) / baseline_avg
        else:
            trend_pct = 0
        features[f"{stat_col}_trend"] = (
            1 if trend_pct > 0.05 else (-1 if trend_pct < -0.05 else 0)
        )
        features[f"{stat_col}_trend_pct"] = trend_pct
    else:
        features[f"{stat_col}_trend"] = 0
        features[f"{stat_col}_trend_pct"] = 0

    # ---- Matchup history vs this opponent.
    matchup_games = games_df[games_df["opponent_team_id"] == opponent_team_id]
    if len(matchup_games) >= 2:
        matchup_avg = matchup_games[stat_col].dropna().mean()
        overall_avg = games_df.head(20)[stat_col].dropna().mean()
        if overall_avg and overall_avg > 0:
            matchup_mult = matchup_avg / overall_avg
        else:
            matchup_mult = 1.0
        features[f"{stat_col}_matchup_avg"] = matchup_avg
        features[f"{stat_col}_matchup_games"] = len(matchup_games)
        features[f"{stat_col}_matchup_mult"] = matchup_mult
    else:
        features[f"{stat_col}_matchup_avg"] = 0
        features[f"{stat_col}_matchup_games"] = 0
        features[f"{stat_col}_matchup_mult"] = 1.0

    # ---- Rest features (days since last game; b2b flag; games in last 7).
    if len(games_df) > 0:
        last_game_date = games_df.iloc[0]["game_date"]
        days_rest = (game_date - last_game_date).days
        week_ago = game_date - timedelta(days=7)
        games_last_week = len(games_df[games_df["game_date"] >= week_ago])
        features["days_rest"] = days_rest
        features["is_b2b"] = 1 if days_rest <= 1 else 0
        features["games_last_7_days"] = games_last_week
    else:
        features["days_rest"] = 2
        features["is_b2b"] = 0
        features["games_last_7_days"] = 0

    # ---- Minutes-derived features.
    minutes = games_df["minutes"].dropna()
    features["avg_minutes_5"] = minutes.head(5).mean() if len(minutes) else 0
    features["avg_minutes_10"] = minutes.head(10).mean() if len(minutes) else 0
    features["minutes_std"] = minutes.head(10).std() if len(minutes) > 1 else 0
    features["is_starter"] = (
        1 if (len(minutes) >= 5 and minutes.head(5).mean() >= 28) else 0
    )

    # ---- Advanced stat 10-game averages (one per column).
    advanced_cols = [
        "usage_percentage",
        "true_shooting_percentage",
        "effective_field_goal_percentage",
        "offensive_rating",
        "defensive_rating",
        "assist_percentage",
        "rebound_percentage",
        "turnover_percentage",
        "plus_minus",
        "pace",
    ]
    for col in advanced_cols:
        if col in games_df.columns:
            recent = games_df.head(10)[col].dropna()
            features[f"{col}_avg"] = recent.mean() if len(recent) > 0 else 0
        else:
            features[f"{col}_avg"] = 0

    # ---- Opponent team defense, as it stood before this game. Tonight that
    # is the pred_team_defense_stats row; for a past game it is what that row
    # would have held then (a training row must not see today's defense).
    defense = _opponent_defense(db, opponent_team_id, game_date)
    defense_col = _OPP_STAT_ALLOWED_COL[stat_col]
    features["opp_def_rating"] = defense.get("defensive_rating") or 0
    features["opp_pace"] = defense.get("pace") or 0
    features["opp_stat_allowed"] = defense.get(defense_col) or 0

    # ---- Vegas lines for this game, found through the opponent: the roster
    # table only knows a player's team today, which is the wrong game for
    # anyone traded since.
    game_line = _game_line_vs(db, opponent_team_id, game_date)
    if game_line is not None:
        line, is_home = game_line
        spread = line.spread_home if is_home else line.spread_away
        features["spread"] = spread if spread else 0
        features["total"] = line.total if line.total else 0
        features["is_home"] = 1 if is_home else 0
        features["is_favorite"] = 1 if spread and spread < 0 else 0
        features["blowout_risk"] = line.get_blowout_risk() if line.spread_home else 0.15
    else:
        features["spread"] = 0
        features["total"] = 0
        features["is_home"] = 0
        features["is_favorite"] = 0
        features["blowout_risk"] = 0.15

    # ---- Calendar context.
    features["month"] = game_date.month

    # ---- Home/away split (signed delta, normalized by overall avg).
    home_games = games_df[games_df["home_game"] == True]  # noqa: E712
    away_games = games_df[games_df["home_game"] == False]  # noqa: E712
    if len(home_games) >= 3 and len(away_games) >= 3:
        home_avg = home_games.head(10)[stat_col].dropna().mean()
        away_avg = away_games.head(10)[stat_col].dropna().mean()
        overall_avg = games_df.head(20)[stat_col].dropna().mean()
        if overall_avg and overall_avg > 0:
            features["home_away_split"] = (home_avg - away_avg) / overall_avg
        else:
            features["home_away_split"] = 0
    else:
        features["home_away_split"] = 0

    return features


def build_points_features(
    db,
    player_id: int,
    game_date: date,
    opponent_team_id: int,
) -> Optional[dict]:
    """Backward-compat wrapper. Calls `build_features(..., stat_col="points")`
    to preserve the existing import in generate_points_predictions.py."""
    return build_features(
        db=db,
        player_id=player_id,
        game_date=game_date,
        opponent_team_id=opponent_team_id,
        stat_col="points",
    )
