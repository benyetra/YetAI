"""Compute expected minutes for today's WNBA active players.

Port of NBA ``update_expected_minutes.py``: recency-weighted average over the
last 30 games, starter/B2B/home-away context, plus minutes redistribution when
star teammates are ruled out.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAPlayerInjuryStatus,
    WNBARecentGames,
    WNBATeamRoster,
    WNBATodayActivePlayers,
)
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba._expected_minutes import (
    LOOKBACK_GAMES,
    MIN_GAMES_REQUIRED,
    ROTATION_MINUTES_L5,
    apply_context_adjustments,
    calc_metrics,
    redistribute_minutes_boost,
)

logger = logging.getLogger(__name__)

INJURY_OUT = frozenset({"out", "ir", "doubtful"})
INJURY_PROB = {
    "out": 1.0,
    "ir": 1.0,
    "doubtful": 0.75,
    "questionable": 0.5,
}

# Backward-compatible aliases for tests importing from this module.
_calc_metrics = calc_metrics
_apply_context_adjustments = apply_context_adjustments


def _recent_avg_minutes(db, player_id: int, *, limit: int = 5) -> float | None:
    games = (
        db.query(WNBARecentGames)
        .filter(
            and_(
                WNBARecentGames.player_id == player_id,
                WNBARecentGames.minutes.isnot(None),
                WNBARecentGames.minutes > 0,
            )
        )
        .order_by(WNBARecentGames.game_date.desc())
        .limit(limit)
        .all()
    )
    if len(games) < 3:
        return None
    return sum(float(g.minutes) for g in games) / len(games)


def _teammate_out_boost(
    db,
    *,
    team_id: int,
    player_id: int,
    base_expected: float,
    active_by_player: dict[int, float],
) -> float:
    """Redistribute minutes from ruled-out rotation teammates (live slate only)."""
    if base_expected <= 0 or not active_by_player:
        return 0.0

    roster = db.query(WNBATeamRoster).filter_by(team_id=team_id).all()
    freed = 0.0
    for teammate in roster:
        if teammate.player_id == player_id:
            continue
        inj = (
            db.query(WNBAPlayerInjuryStatus)
            .filter_by(player_id=teammate.player_id)
            .first()
        )
        status = (inj.status or "").lower() if inj else ""
        if status not in INJURY_OUT:
            continue
        avg_min = _recent_avg_minutes(db, teammate.player_id)
        if avg_min is None or avg_min < ROTATION_MINUTES_L5:
            continue
        freed += avg_min * INJURY_PROB.get(status, 1.0)

    if freed <= 0:
        return 0.0

    pool_total = sum(active_by_player.values())
    return redistribute_minutes_boost(
        base_expected, freed_minutes=freed, active_pool_total=pool_total
    )


def _load_recent_games(db, player_id: int) -> list:
    return (
        db.query(WNBARecentGames)
        .filter(
            and_(
                WNBARecentGames.player_id == player_id,
                WNBARecentGames.minutes.isnot(None),
                WNBARecentGames.minutes > 0,
            )
        )
        .order_by(WNBARecentGames.game_date.desc())
        .limit(LOOKBACK_GAMES)
        .all()
    )


def expected_minutes_for_player(
    db,
    *,
    player_id: int,
    team_id: int,
    game_date: date,
    home_game: bool | None,
    active_by_player: dict[int, float],
) -> float | None:
    """Live slate expected minutes including teammate-out redistribution."""
    metrics = calc_metrics(_load_recent_games(db, player_id))
    if metrics is None:
        return None

    adjusted = apply_context_adjustments(
        metrics, game_date=game_date, home_game=home_game
    )
    boost = _teammate_out_boost(
        db,
        team_id=team_id,
        player_id=player_id,
        base_expected=adjusted,
        active_by_player=active_by_player,
    )
    return round(max(0.0, adjusted + boost), 1)


def run() -> dict:
    today = now_eastern().date()
    db = SessionLocal()
    updated = 0
    skipped_thin = 0
    boost_applied = 0

    try:
        active_rows = (
            db.query(WNBATodayActivePlayers)
            .filter(WNBATodayActivePlayers.game_date == today)
            .all()
        )

        baselines: dict[int, float] = {}
        for row in active_rows:
            metrics = calc_metrics(_load_recent_games(db, row.player_id))
            if metrics is None:
                continue
            baselines[row.player_id] = apply_context_adjustments(
                metrics, game_date=today, home_game=row.home_game
            )

        for row in active_rows:
            base = baselines.get(row.player_id)
            if base is None:
                skipped_thin += 1
                row.expected_minutes = None
                continue

            boost = _teammate_out_boost(
                db,
                team_id=row.team_id,
                player_id=row.player_id,
                base_expected=base,
                active_by_player=baselines,
            )
            if boost > 0:
                boost_applied += 1
            row.expected_minutes = round(max(0.0, base + boost), 1)
            updated += 1

        db.commit()
        return {
            "status": "ok",
            "players_updated": updated,
            "players_skipped_thin_data": skipped_thin,
            "teammate_boost_applied": boost_applied,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
