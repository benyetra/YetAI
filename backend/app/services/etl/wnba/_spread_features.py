"""Game-level features for WNBA spread ML (player availability + team ratings)."""

from __future__ import annotations

from datetime import date

from app.models.predictions_models import (
    WNBAPlayerInjuryStatus,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
    WNBATodayActivePlayers,
)
from app.services.etl._spread_model import (
    WNBA_CONFIG,
    expected_margin,
    load_elos_from_actuals,
    pace_overlay_adjustment,
)
from app.services.etl.wnba._espn import now_eastern

INJURY_OUT_STATUSES = frozenset({"out", "ir", "doubtful"})


def _team_minutes_and_injuries(
    db, *, team_name: str, game_date: date
) -> tuple[float, int, int]:
    """Sum expected minutes, count active, count ruled-out on roster."""
    active = (
        db.query(WNBATodayActivePlayers)
        .filter(
            WNBATodayActivePlayers.game_date == game_date,
            WNBATodayActivePlayers.team_name == team_name,
        )
        .all()
    )
    minutes_sum = 0.0
    out_count = 0
    for row in active:
        inj = (
            db.query(WNBAPlayerInjuryStatus)
            .filter(WNBAPlayerInjuryStatus.player_id == row.player_id)
            .first()
        )
        status = (inj.status or "").lower() if inj else ""
        if status in INJURY_OUT_STATUSES:
            out_count += 1
            continue
        minutes_sum += float(row.expected_minutes or 0.0)
    return minutes_sum, len(active), out_count


def build_game_features(
    db,
    *,
    game_date: date,
    home_team_name: str,
    away_team_name: str,
    home_team_id: int | None,
    away_team_id: int | None,
    market_spread_home: float | None,
    market_total: float | None,
    spread_actuals_model,
) -> dict[str, float] | None:
    """Feature vector for one game; None if Elo history is empty."""
    actuals = (
        db.query(spread_actuals_model)
        .filter(spread_actuals_model.game_date < game_date)
        .order_by(spread_actuals_model.game_date.asc())
        .all()
    )
    elos = load_elos_from_actuals(actuals, cfg=WNBA_CONFIG)
    home_elo = elos.get(home_team_name, WNBA_CONFIG.initial_elo)
    away_elo = elos.get(away_team_name, WNBA_CONFIG.initial_elo)
    base_margin = expected_margin(home_elo, away_elo, cfg=WNBA_CONFIG)

    offense_by_name = {o.team_name: o for o in db.query(WNBATeamOffenseStats).all()}
    defense_by_name = {d.team_name: d for d in db.query(WNBATeamDefenseStats).all()}
    home_off = offense_by_name.get(home_team_name)
    home_def = defense_by_name.get(home_team_name)
    away_off = offense_by_name.get(away_team_name)
    away_def = defense_by_name.get(away_team_name)
    pace_adj = pace_overlay_adjustment(
        home_off.points_per_game if home_off else None,
        home_def.points_allowed_per_game if home_def else None,
        away_off.points_per_game if away_off else None,
        away_def.points_allowed_per_game if away_def else None,
        cfg=WNBA_CONFIG,
    )

    home_mins, home_active, home_out = _team_minutes_and_injuries(
        db, team_name=home_team_name, game_date=game_date
    )
    away_mins, away_active, away_out = _team_minutes_and_injuries(
        db, team_name=away_team_name, game_date=game_date
    )

    return {
        "elo_diff": home_elo - away_elo,
        "base_margin": base_margin,
        "pace_adj": pace_adj,
        "elo_pace_margin": base_margin + pace_adj,
        "home_expected_minutes": home_mins,
        "away_expected_minutes": away_mins,
        "minutes_diff": home_mins - away_mins,
        "home_active_count": float(home_active),
        "away_active_count": float(away_active),
        "home_out_count": float(home_out),
        "away_out_count": float(away_out),
        "injury_diff": float(away_out - home_out),
        "home_ppg": float(home_off.points_per_game or 0.0) if home_off else 0.0,
        "away_ppg": float(away_off.points_per_game or 0.0) if away_off else 0.0,
        "home_papg": (
            float(home_def.points_allowed_per_game or 0.0) if home_def else 0.0
        ),
        "away_papg": (
            float(away_def.points_allowed_per_game or 0.0) if away_def else 0.0
        ),
        "market_spread_home": float(market_spread_home or 0.0),
        "market_total": float(market_total or 0.0),
        "home_team_id": float(home_team_id or 0),
        "away_team_id": float(away_team_id or 0),
        "day_of_year": float(game_date.timetuple().tm_yday),
        "is_today": 1.0 if game_date == now_eastern().date() else 0.0,
    }
