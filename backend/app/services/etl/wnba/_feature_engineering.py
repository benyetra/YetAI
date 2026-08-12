"""Per-player WNBA feature extraction for XGBoost projection models.

Scoped to points, assists, rebounds. Returns a flat dict keyed by feature name;
the model's metadata.json controls feature ordering at inference time.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta

from sqlalchemy import or_

from app.models.predictions_models import (
    WNBAGameLines,
    WNBARecentGames,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
    WNBATeamRoster,
)
from app.services.etl.wnba._expected_minutes import (
    LOOKBACK_GAMES,
    historical_expected_minutes,
    is_home_bool,
)
from app.services.etl.wnba._shooting_metrics import shooting_from_row
from app.services.etl.wnba._training_context import TrainingContext

logger = logging.getLogger(__name__)

LEAGUE_AVG_PACE = 80.0
MIN_GAMES_REQUIRED = 5
STARTER_MINUTES_L5 = 28.0
SUPPORTED_STATS: tuple[str, ...] = ("points", "assists", "rebounds", "three_pt_made")

_OPP_STAT_ALLOWED_COL: dict[str, str] = {
    "points": "points_allowed_per_game",
    "assists": "assists_allowed_per_game",
    "rebounds": "rebounds_allowed_per_game",
    "three_pt_made": "three_pt_made_allowed_per_game",
}

_ADVANCED_AVG_COLS: tuple[str, ...] = (
    "usage_percentage",
    "true_shooting_percentage",
    "effective_field_goal_percentage",
    "offensive_rating",
    "defensive_rating",
    "assist_percentage",
    "plus_minus",
    "pace",
)


def _avg_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _std_or_zero(values: list[float | None]) -> float:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return 0.0
    return float(statistics.pstdev(vals))


def _player_team_name(db, player_id: int) -> str:
    roster = db.query(WNBATeamRoster).filter_by(player_id=player_id).first()
    if not roster:
        return ""
    team_stats = (
        db.query(WNBATeamOffenseStats).filter_by(team_id=roster.team_id).first()
    )
    return team_stats.team_name if team_stats else ""


def _game_line_values(
    game_line: WNBAGameLines | None,
    *,
    opponent_team_id: int,
    team_name: str,
) -> tuple[float, float, float, float]:
    """Return (market_total, market_spread, is_home, is_favorite)."""
    if not game_line:
        return 0.0, 0.0, 0.0, 0.0

    is_home = 0.0
    if team_name and game_line.home_team_name:
        is_home = 1.0 if team_name.lower() in game_line.home_team_name.lower() else 0.0
    elif game_line.away_team_id == opponent_team_id:
        is_home = 1.0
    elif game_line.home_team_id == opponent_team_id:
        is_home = 0.0

    spread = game_line.spread_home if is_home else game_line.spread_away
    spread_val = float(spread or 0.0)
    total_val = float(game_line.total or 0.0)
    is_favorite = 1.0 if spread_val < 0 else 0.0
    return total_val, spread_val, is_home, is_favorite


def _game_line_context(
    db,
    *,
    game_date: date,
    opponent_team_id: int,
    team_name: str,
) -> tuple[float, float, float, float]:
    """Return (market_total, market_spread, is_home, is_favorite)."""
    game_line = (
        db.query(WNBAGameLines)
        .filter(
            WNBAGameLines.game_date == game_date,
            or_(
                WNBAGameLines.home_team_id == opponent_team_id,
                WNBAGameLines.away_team_id == opponent_team_id,
                WNBAGameLines.home_team_name.ilike(f"%{team_name}%"),
                WNBAGameLines.away_team_name.ilike(f"%{team_name}%"),
            ),
        )
        .first()
    )
    return _game_line_values(
        game_line, opponent_team_id=opponent_team_id, team_name=team_name
    )


def build_features(
    db,
    *,
    stat_col: str,
    player_id: int,
    game_date: date,
    opponent_team_id: int,
    ctx: TrainingContext | None = None,
) -> dict[str, float] | None:
    """Return feature dict, or None if the player has too thin a history."""
    if stat_col not in SUPPORTED_STATS:
        raise ValueError(f"unsupported stat: {stat_col}")

    if ctx is not None:
        recent = ctx.recent_games_before(player_id, game_date)
    else:
        recent = (
            db.query(WNBARecentGames)
            .filter(
                WNBARecentGames.player_id == player_id,
                WNBARecentGames.game_date < game_date,
            )
            .order_by(WNBARecentGames.game_date.desc())
            .limit(LOOKBACK_GAMES)
            .all()
        )
    if len(recent) < MIN_GAMES_REQUIRED:
        return None

    def stat(g, col):
        v = getattr(g, col, None)
        return float(v) if v is not None else None

    def shooting_stat(g, col: str) -> float | None:
        derived = shooting_from_row(g)
        val = derived.get(col)
        if val is not None:
            return val
        return stat(g, col)

    features: dict[str, float] = {}

    # Rolling windows (keep legacy l3/l5/l10 names for existing models)
    for window in (3, 5, 10):
        stat_vals = [stat(g, stat_col) for g in recent[:window]]
        min_vals = [stat(g, "minutes") for g in recent[:window]]
        features[f"{stat_col}_l{window}"] = _avg_or_none(stat_vals) or 0.0
        features[f"minutes_l{window}"] = _avg_or_none(min_vals) or 0.0

    features[f"{stat_col}_std_l5"] = _std_or_zero(
        [stat(g, stat_col) for g in recent[:5]]
    )
    features[f"{stat_col}_std_l10"] = _std_or_zero(
        [stat(g, stat_col) for g in recent[:10]]
    )
    features["minutes_std_l10"] = _std_or_zero(
        [stat(g, "minutes") for g in recent[:10]]
    )

    # Season averages (use recent games as a season proxy)
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
        _avg_or_none([shooting_stat(g, "true_shooting_percentage") for g in recent])
        or 0.0
    )
    features["season_efg_pct"] = (
        _avg_or_none(
            [shooting_stat(g, "effective_field_goal_percentage") for g in recent]
        )
        or 0.0
    )

    # Shooting efficiency + volume (points model signal; derived from box score)
    for window in (3, 5, 10):
        features[f"efg_l{window}"] = (
            _avg_or_none(
                [
                    shooting_stat(g, "effective_field_goal_percentage")
                    for g in recent[:window]
                ]
            )
            or 0.0
        )
        features[f"ts_l{window}"] = (
            _avg_or_none(
                [shooting_stat(g, "true_shooting_percentage") for g in recent[:window]]
            )
            or 0.0
        )
        features[f"fga_l{window}"] = (
            _avg_or_none([stat(g, "fg_attempts") for g in recent[:window]]) or 0.0
        )

    # Trend: recent 5 vs 10-game baseline
    l5_avg = features[f"{stat_col}_l5"]
    l10_avg = features[f"{stat_col}_l10"]
    if l10_avg > 0:
        trend_pct = (l5_avg - l10_avg) / l10_avg
    else:
        trend_pct = 0.0
    features[f"{stat_col}_trend_pct"] = trend_pct
    features[f"{stat_col}_trend"] = (
        1.0 if trend_pct > 0.05 else (-1.0 if trend_pct < -0.05 else 0.0)
    )

    # Matchup history vs this opponent
    matchup = [g for g in recent if g.opponent_team_id == opponent_team_id]
    if len(matchup) >= 2:
        matchup_avg = _avg_or_none([stat(g, stat_col) for g in matchup]) or 0.0
        overall_avg = features[f"season_{stat_col}_avg"]
        matchup_mult = matchup_avg / overall_avg if overall_avg > 0 else 1.0
        features[f"{stat_col}_matchup_avg"] = matchup_avg
        features[f"{stat_col}_matchup_games"] = float(len(matchup))
        features[f"{stat_col}_matchup_mult"] = matchup_mult
    else:
        features[f"{stat_col}_matchup_avg"] = 0.0
        features[f"{stat_col}_matchup_games"] = 0.0
        features[f"{stat_col}_matchup_mult"] = 1.0

    # Minutes / role — historical replay of weighted expected minutes
    if ctx is not None:
        team_name = ctx.player_team_name(player_id)
        game_line = ctx.game_line_for_team(game_date, opponent_team_id, team_name)
        market_total, market_spread, is_home, is_favorite = _game_line_values(
            game_line, opponent_team_id=opponent_team_id, team_name=team_name
        )
    else:
        team_name = _player_team_name(db, player_id)
        market_total, market_spread, is_home, is_favorite = _game_line_context(
            db,
            game_date=game_date,
            opponent_team_id=opponent_team_id,
            team_name=team_name,
        )
    home_game = is_home_bool(is_home, team_name=team_name)
    freed_minutes = 0.0
    active_pool_total: float | None = None
    if ctx is not None:
        freed_minutes, active_pool_total = ctx.teammate_out_boost_inputs(
            player_id, game_date
        )
        if active_pool_total <= 0:
            active_pool_total = None
    expected = historical_expected_minutes(
        recent,
        game_date=game_date,
        home_game=home_game,
        freed_minutes=freed_minutes,
        active_pool_total=active_pool_total,
    )
    if expected is None:
        expected = features["minutes_l5"]
    features["expected_minutes"] = expected
    features["minutes_delta_l5"] = expected - features["minutes_l5"]
    features["is_starter"] = 1.0 if expected >= STARTER_MINUTES_L5 else 0.0

    # Advanced 10-game averages (eFG/TS derived when DB column is null)
    for col in _ADVANCED_AVG_COLS:
        if col in ("effective_field_goal_percentage", "true_shooting_percentage"):
            vals = [shooting_stat(g, col) for g in recent[:10]]
        else:
            vals = [stat(g, col) for g in recent[:10]]
        features[f"{col}_avg"] = _avg_or_none(vals) or 0.0

    # Opponent defense / pace
    if ctx is not None:
        opp_def = ctx.opponent_defense(opponent_team_id)
        opp_off = ctx.opponent_offense(opponent_team_id)
    else:
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

    # Context: rest days, schedule density
    last_game = recent[0]
    rest = (game_date - last_game.game_date).days
    week_ago = game_date - timedelta(days=7)
    games_last_7 = sum(1 for g in recent if g.game_date >= week_ago)
    features["rest_days"] = float(rest)
    features["is_back_to_back"] = 1.0 if rest <= 1 else 0.0
    features["games_last_7_days"] = float(games_last_7)

    # Pace factor (game's projected pace ÷ league avg)
    features["pace_factor"] = (
        (opp_off.pace / LEAGUE_AVG_PACE) if (opp_off and opp_off.pace) else 1.0
    )

    # Home/away split from recent games
    home_games = [g for g in recent if g.home_game is True]
    away_games = [g for g in recent if g.home_game is False]
    if len(home_games) >= 3 and len(away_games) >= 3:
        home_avg = _avg_or_none([stat(g, stat_col) for g in home_games[:10]]) or 0.0
        away_avg = _avg_or_none([stat(g, stat_col) for g in away_games[:10]]) or 0.0
        overall_avg = features[f"season_{stat_col}_avg"]
        features["home_away_split"] = (
            (home_avg - away_avg) / overall_avg if overall_avg > 0 else 0.0
        )
    else:
        features["home_away_split"] = 0.0

    # Vegas context for today's game
    features["market_total"] = market_total
    features["market_spread"] = market_spread
    features["is_home"] = is_home
    features["is_favorite"] = is_favorite
    features["month"] = float(game_date.month)

    return features


def apply_expected_minutes(
    features: dict[str, float], expected_minutes: float | None
) -> dict[str, float]:
    """Overlay live expected minutes from today_active_players before inference."""
    if expected_minutes is None:
        return features
    out = dict(features)
    out["expected_minutes"] = float(expected_minutes)
    out["minutes_delta_l5"] = float(expected_minutes) - out.get("minutes_l5", 0.0)
    return out
