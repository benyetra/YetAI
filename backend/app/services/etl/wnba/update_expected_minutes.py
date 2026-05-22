"""Compute expected minutes per active WNBA player using the L5 rolling average.

Writes to pred_wnba_today_active_players.expected_minutes. Players with
fewer than 3 recent games are left as None (do not project on too-thin data —
inference will then skip them).
"""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models.predictions_models import WNBARecentGames, WNBATodayActivePlayers
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)

L5_WINDOW = 5
MIN_GAMES_REQUIRED = 3


def run() -> dict:
    today = now_eastern().date()
    db = SessionLocal()
    updated = 0
    skipped_thin = 0
    try:
        active = db.query(WNBATodayActivePlayers).filter(
            WNBATodayActivePlayers.game_date == today
        ).all()
        for row in active:
            recent = (
                db.query(WNBARecentGames)
                .filter(WNBARecentGames.player_id == row.player_id)
                .order_by(WNBARecentGames.game_date.desc())
                .limit(L5_WINDOW)
                .all()
            )
            valid_minutes = [g.minutes for g in recent if g.minutes is not None]
            if len(valid_minutes) < MIN_GAMES_REQUIRED:
                skipped_thin += 1
                row.expected_minutes = None
                continue
            row.expected_minutes = sum(valid_minutes) / len(valid_minutes)
            updated += 1
        db.commit()
        return {
            "status": "ok",
            "players_updated": updated,
            "players_skipped_thin_data": skipped_thin,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
