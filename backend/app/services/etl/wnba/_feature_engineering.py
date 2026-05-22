"""Per-player WNBA feature extraction for XGBoost projection models.

Scoped to points, assists, rebounds. Returns a flat dict keyed by feature name;
the model's metadata.json controls feature ordering at inference time.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from app.models.predictions_models import (
    WNBAGameLines,
    WNBARecentGames,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
)

logger = logging.getLogger(__name__)

LEAGUE_AVG_PACE = 80.0
MIN_GAMES_REQUIRED = 5
SUPPORTED_STATS: tuple[str, ...] = ("points", "assists", "rebounds")

_OPP_STAT_ALLOWED_COL: dict[str, str] = {
    "points": "points_allowed_per_game",
    "assists": "assists_allowed_per_game",
    "rebounds": "rebounds_allowed_per_game",
}


def _avg_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_features(
    db,
    *,
    stat_col: str,
    player_id: int,
    game_date: date,
    opponent_team_id: int,
) -> dict[str, float] | None:
    """Return feature dict, or None if the player has too thin a history."""
    if stat_col not in SUPPORTED_STATS:
        raise ValueError(f"unsupported stat: {stat_col}")

    recent = (
        db.query(WNBARecentGames)
        .filter(
            WNBARecentGames.player_id == player_id,
            WNBARecentGames.game_date < game_date,
        )
        .order_by(WNBARecentGames.game_date.desc())
        .limit(20)
        .all()
    )
    if len(recent) < MIN_GAMES_REQUIRED:
        return None

    def stat(g, col):
        v = getattr(g, col, None)
        return float(v) if v is not None else None

    features: dict[str, float] = {}

    # Rolling windows
    for window in (3, 5, 10):
        features[f"{stat_col}_l{window}"] = (
            _avg_or_none([stat(g, stat_col) for g in recent[:window]]) or 0.0
        )
        features[f"minutes_l{window}"] = (
            _avg_or_none([stat(g, "minutes") for g in recent[:window]]) or 0.0
        )

    # Season averages (use all 20 recent games as a season proxy)
    features[f"season_{stat_col}_avg"] = (
        _avg_or_none([stat(g, stat_col) for g in recent]) or 0.0
    )
    features["season_minutes_avg"] = (
        _avg_or_none([stat(g, "minutes") for g in recent]) or 0.0
    )
    features["season_usage_pct"] = (
        _avg_or_none([stat(g, "usage_percentage") for g in recent]) or 0.0
    )
    features["season_ts_pct"] = (
        _avg_or_none([stat(g, "true_shooting_percentage") for g in recent]) or 0.0
    )

    # Opponent defense
    opp_def = (
        db.query(WNBATeamDefenseStats)
        .filter(WNBATeamDefenseStats.team_id == opponent_team_id)
        .first()
    )
    opp_off = (
        db.query(WNBATeamOffenseStats)
        .filter(WNBATeamOffenseStats.team_id == opponent_team_id)
        .first()
    )
    opp_col = _OPP_STAT_ALLOWED_COL[stat_col]
    features[f"opp_{opp_col}"] = (
        (getattr(opp_def, opp_col, None) or 0.0) if opp_def else 0.0
    )
    features["opp_defensive_rating"] = (
        (opp_def.defensive_rating or 0.0) if opp_def else 0.0
    )
    features["opp_pace"] = (
        (opp_off.pace or LEAGUE_AVG_PACE) if opp_off else LEAGUE_AVG_PACE
    )

    # Context: rest days, back-to-back flag
    last_game = recent[0]
    rest = (game_date - last_game.game_date).days
    features["rest_days"] = float(rest)
    features["is_back_to_back"] = 1.0 if rest <= 1 else 0.0

    # Pace factor (game's projected pace ÷ league avg)
    features["pace_factor"] = (
        (opp_off.pace / LEAGUE_AVG_PACE) if (opp_off and opp_off.pace) else 1.0
    )

    return features
