"""Generate per-player WNBA rebounds projections for today's slate."""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAPlayerInjuryStatus,
    WNBAReboundsProjections,
    WNBATodayActivePlayers,
)
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba._feature_engineering import build_features
from app.services.etl.wnba._ml_predict import predict

logger = logging.getLogger(__name__)

INJURY_SKIP = {"out", "ir", "doubtful"}
STAT = "rebounds"


def run() -> dict:
    today = now_eastern().date()
    db = SessionLocal()
    written = 0
    skipped_injured = 0
    skipped_thin = 0
    try:
        active_rows = (
            db.query(WNBATodayActivePlayers)
            .filter(WNBATodayActivePlayers.game_date == today)
            .all()
        )
        for p in active_rows:
            inj = (
                db.query(WNBAPlayerInjuryStatus)
                .filter(WNBAPlayerInjuryStatus.player_id == p.player_id)
                .first()
            )
            if inj and (inj.status or "").lower() in INJURY_SKIP:
                skipped_injured += 1
                continue
            feats = build_features(
                db, stat_col=STAT, player_id=p.player_id,
                game_date=today, opponent_team_id=p.opponent_team_id,
            )
            if feats is None:
                skipped_thin += 1
                continue
            try:
                projected = predict(STAT, feats)
            except Exception as exc:
                logger.warning("predict failed for player %s: %s", p.player_id, exc)
                continue
            db.merge(WNBAReboundsProjections(
                date=today,
                player_id=p.player_id,
                player_name=p.player_name,
                opponent_team_name=p.opponent_team_name,
                projected_rebounds=projected,
                market_line=None,
                edge=None,
                recommendation="NO_PLAY",
                confidence_score=None,
                created_at=datetime.utcnow(),
            ))
            written += 1
        db.commit()
        return {
            "status": "ok",
            "date": today.isoformat(),
            "projections_written": written,
            "skipped_injured": skipped_injured,
            "skipped_thin_history": skipped_thin,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
