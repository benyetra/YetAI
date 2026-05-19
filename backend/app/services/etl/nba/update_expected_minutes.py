"""Compute pred_player_expected_minutes from pred_recent_games (Development-1nt).

Port of YetiBets/scripts/nba/update_expected_minutes.py. Pure-Python calc:
weighted recency average + std-dev + starter/B2B/home/away splits over the
last 30 games with minutes>0. Targets today's active players first, falls
back to the whole roster if pred_today_active_players is empty.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.predictions_models import (
    PlayerExpectedMinutes,
    RecentGames,
    TeamRoster,
    TodayActivePlayers,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)

# Recency weights for last_10 games (most recent first). Sum is < 1; remaining
# games beyond 10 get a flat 0.01 each. Preserved from YetiBets's hand-tuned curve.
RECENCY_WEIGHTS = [0.25, 0.20, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05, 0.025, 0.025]


def _calc_for(db, player_id: int, player_name: str) -> dict | None:
    games = (
        db.query(RecentGames)
        .filter(and_(
            RecentGames.player_id == player_id,
            RecentGames.minutes.isnot(None),
            RecentGames.minutes > 0,
        ))
        .order_by(RecentGames.game_date.desc())
        .limit(30)
        .all()
    )
    if len(games) < 5:
        return None

    all_minutes = [g.minutes for g in games]
    last_5 = all_minutes[:5]
    last_10 = all_minutes[:10]

    avg_5 = sum(last_5) / len(last_5)
    avg_10 = sum(last_10) / len(last_10)
    avg_season = sum(all_minutes) / len(all_minutes)

    variance = sum((x - avg_10) ** 2 for x in last_10) / len(last_10)
    std_dev = math.sqrt(variance)

    is_starter = avg_5 >= 28
    starter_rate = sum(1 for m in last_10 if m >= 25) / len(last_10)

    # Back-to-back patterns: any game where the day before also had one.
    b2b = []
    for i in range(len(games) - 1):
        if (games[i].game_date - games[i + 1].game_date).days == 1:
            b2b.append(games[i].minutes)
    b2b_avg = sum(b2b) / len(b2b) if b2b else None

    home = [g.minutes for g in games if g.home_game is True]
    away = [g.minutes for g in games if g.home_game is False]
    home_avg = sum(home) / len(home) if len(home) >= 3 else None
    away_avg = sum(away) / len(away) if len(away) >= 3 else None

    weighted_sum = 0.0
    total_weight = 0.0
    for i, m in enumerate(last_10):
        w = RECENCY_WEIGHTS[i] if i < len(RECENCY_WEIGHTS) else 0.01
        weighted_sum += m * w
        total_weight += w
    expected_today = weighted_sum / total_weight if total_weight else avg_10

    consistency = 1 / (1 + std_dev / 10)
    recency_weight = 0.8 if len(last_5) >= 5 else 0.5
    confidence = max(0.3, min(consistency * 0.6 + recency_weight * 0.4, 1.0))

    return {
        "avg_minutes_5": round(avg_5, 1),
        "avg_minutes_10": round(avg_10, 1),
        "avg_minutes_season": round(avg_season, 1),
        "minutes_std_dev": round(std_dev, 2),
        "min_minutes_10": round(min(last_10), 1),
        "max_minutes_10": round(max(last_10), 1),
        "is_starter": is_starter,
        "starter_rate": round(starter_rate, 2),
        "b2b_minutes_avg": round(b2b_avg, 1) if b2b_avg is not None else None,
        "home_minutes_avg": round(home_avg, 1) if home_avg is not None else None,
        "away_minutes_avg": round(away_avg, 1) if away_avg is not None else None,
        "expected_minutes_today": round(expected_today, 1),
        "minutes_confidence": round(confidence, 2),
    }


def run() -> dict:
    today = now_eastern().date()
    created = 0
    updated = 0
    skipped = 0

    db = SessionLocal()
    try:
        active = (
            db.query(TodayActivePlayers.player_id, TodayActivePlayers.player_name)
            .filter(TodayActivePlayers.game_date == today)
            .all()
        )
        if active:
            player_list = active
            source = "today_active_players"
        else:
            roster = db.query(TeamRoster.player_id, TeamRoster.player_name).all()
            player_list = roster
            source = "team_roster_fallback"

        for pid, pname in player_list:
            try:
                metrics = _calc_for(db, pid, pname)
                if metrics is None:
                    skipped += 1
                    continue
                existing = db.query(PlayerExpectedMinutes).filter_by(player_id=pid).first()
                if existing:
                    for k, v in metrics.items():
                        setattr(existing, k, v)
                    existing.last_updated = datetime.utcnow()
                    updated += 1
                else:
                    db.add(PlayerExpectedMinutes(
                        player_id=pid,
                        player_name=pname,
                        **metrics,
                        last_updated=datetime.utcnow(),
                    ))
                    created += 1
                db.commit()
            except Exception:
                logger.exception("update_expected_minutes: failed for %s", pname)
                db.rollback()
                continue

        return {
            "status": "ok",
            "source": source,
            "players_considered": len(player_list),
            "created": created,
            "updated": updated,
            "skipped_insufficient_data": skipped,
        }
    finally:
        db.close()
