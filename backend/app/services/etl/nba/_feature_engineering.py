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

import pandas as pd
from sqlalchemy import and_, or_

from app.models.predictions_models import (
    NBAGameLines,
    RecentGames,
    TeamDefenseStats,
    TeamOffenseStats,
    TeamRoster,
)

logger = logging.getLogger(__name__)


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
        game_date: target game date (features use only games BEFORE this)
        opponent_team_id: NBA.com opponent team_id
        stat_col: target stat key — one of the keys in _OPP_STAT_ALLOWED_COL

    Returns:
        A dict keyed by the training-time feature names, or None if the player
        has fewer than 5 historical games (insufficient data — caller should
        skip).
    """
    if stat_col not in _OPP_STAT_ALLOWED_COL:
        raise ValueError(
            f"Unknown stat_col {stat_col!r}; supported: "
            f"{sorted(_OPP_STAT_ALLOWED_COL)}"
        )

    historical_games = (
        db.query(RecentGames)
        .filter(
            and_(
                RecentGames.player_id == player_id,
                RecentGames.game_date < game_date,
            )
        )
        .order_by(RecentGames.game_date.desc())
        .limit(50)
        .all()
    )
    if len(historical_games) < 5:
        return None

    games_df = _games_to_df(historical_games)

    features: dict = {}

    # Player's team — used to find the Vegas line and the home/away flag.
    roster = db.query(TeamRoster).filter_by(player_id=player_id).first()
    team_id = roster.team_id if roster else None
    team_name = ""
    if team_id:
        team_stats = db.query(TeamOffenseStats).filter_by(team_id=team_id).first()
        team_name = team_stats.team_name if team_stats else ""

    # ---- Rolling avg/std for the target stat across 5/10/20-game windows.
    for window in [5, 10, 20]:
        if len(games_df) >= window:
            recent = games_df.head(window)[stat_col].dropna()
            if len(recent) > 0:
                features[f"{stat_col}_avg_{window}"] = recent.mean()
                features[f"{stat_col}_std_{window}"] = (
                    recent.std() if len(recent) > 1 else 0
                )
            else:
                features[f"{stat_col}_avg_{window}"] = 0
                features[f"{stat_col}_std_{window}"] = 0
        else:
            features[f"{stat_col}_avg_{window}"] = 0
            features[f"{stat_col}_std_{window}"] = 0

    # ---- Rolling avg/std for minutes across 5/10-game windows.
    for window in [5, 10]:
        if len(games_df) >= window:
            recent = games_df.head(window)["minutes"].dropna()
            if len(recent) > 0:
                features[f"minutes_avg_{window}"] = recent.mean()
                features[f"minutes_std_{window}"] = (
                    recent.std() if len(recent) > 1 else 0
                )
            else:
                features[f"minutes_avg_{window}"] = 0
                features[f"minutes_std_{window}"] = 0
        else:
            features[f"minutes_avg_{window}"] = 0
            features[f"minutes_std_{window}"] = 0

    # ---- Trend: 5-game vs 20-game baseline.
    if len(games_df) >= 20:
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
    if len(games_df) >= 5:
        minutes = games_df["minutes"].dropna()
        features["avg_minutes_5"] = minutes.head(5).mean() if len(minutes) >= 5 else 0
        features["avg_minutes_10"] = (
            minutes.head(10).mean() if len(minutes) >= 10 else 0
        )
        features["minutes_std"] = minutes.head(10).std() if len(minutes) >= 10 else 0
        features["is_starter"] = (
            1 if (len(minutes) >= 5 and minutes.head(5).mean() >= 28) else 0
        )
    else:
        features["avg_minutes_5"] = 0
        features["avg_minutes_10"] = 0
        features["minutes_std"] = 0
        features["is_starter"] = 0

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

    # ---- Opponent team defense.
    defense = db.query(TeamDefenseStats).filter_by(team_id=opponent_team_id).first()
    if defense:
        features["opp_def_rating"] = getattr(defense, "defensive_rating", None) or 0
        features["opp_pace"] = getattr(defense, "pace", None) or 0
        defense_col = _OPP_STAT_ALLOWED_COL[stat_col]
        features["opp_stat_allowed"] = getattr(defense, defense_col, None) or 0
    else:
        features["opp_def_rating"] = 0
        features["opp_pace"] = 0
        features["opp_stat_allowed"] = 0

    # ---- Vegas lines for this game (matched by team-name substring).
    game_line = None
    if team_name:
        game_line = (
            db.query(NBAGameLines)
            .filter(
                and_(
                    NBAGameLines.game_date == game_date,
                    or_(
                        NBAGameLines.home_team_name.ilike(f"%{team_name}%"),
                        NBAGameLines.away_team_name.ilike(f"%{team_name}%"),
                    ),
                )
            )
            .first()
        )

    if game_line:
        is_home = (
            team_name.lower() in (game_line.home_team_name or "").lower()
            if game_line.home_team_name
            else False
        )
        spread = game_line.spread_home if is_home else game_line.spread_away
        features["spread"] = spread if spread else 0
        features["total"] = game_line.total if game_line.total else 0
        features["is_home"] = 1 if is_home else 0
        features["is_favorite"] = 1 if spread and spread < 0 else 0
        features["blowout_risk"] = (
            game_line.get_blowout_risk() if game_line.spread_home else 0.15
        )
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
