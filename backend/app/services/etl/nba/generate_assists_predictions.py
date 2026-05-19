"""Generate per-player assists projections via the XGBoost model.

Mirrors generate_points_predictions.py but targets the assists model and
writes to pred_assists_projections. AssistsProjections has no FanDuel
columns.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import (
    AssistsProjections,
    PlayerInjuryStatus,
    TodayActivePlayers,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._feature_engineering import build_features
from app.services.etl.nba._ml_predict import predict

logger = logging.getLogger(__name__)

STAT = "assists"
INJURY_SKIP_STATUSES = {"out", "ir", "doubtful"}


def _is_injured(db, player_id: int) -> tuple[bool, str | None]:
    injury = (
        db.query(PlayerInjuryStatus)
        .filter(PlayerInjuryStatus.player_id == player_id)
        .first()
    )
    if injury and (injury.status or "").lower() in INJURY_SKIP_STATUSES:
        return True, injury.status
    return False, None


def run() -> dict:
    today = now_eastern().date()
    created = 0
    updated = 0
    skipped_injured = 0
    skipped_insufficient = 0
    errors = 0

    db = SessionLocal()
    try:
        active = (
            db.query(TodayActivePlayers)
            .filter(TodayActivePlayers.game_date == today)
            .all()
        )

        if not active:
            logger.info(
                "generate_%s_predictions: no active players for %s", STAT, today
            )
            return {
                "status": "ok",
                "date": today.isoformat(),
                "players_considered": 0,
                "created": 0,
                "updated": 0,
                "skipped_injured": 0,
                "skipped_insufficient_data": 0,
                "errors": 0,
            }

        for player in active:
            try:
                injured, injury_status = _is_injured(db, player.player_id)
                if injured:
                    skipped_injured += 1
                    continue

                features = build_features(
                    db=db,
                    player_id=player.player_id,
                    game_date=today,
                    opponent_team_id=player.opponent_team_id,
                    stat_col=STAT,
                )
                if features is None:
                    skipped_insufficient += 1
                    continue

                prediction = predict(STAT, features)
                projected = max(0.0, round(prediction, 2))

                existing = (
                    db.query(AssistsProjections)
                    .filter(
                        AssistsProjections.date == today,
                        AssistsProjections.player_id == player.player_id,
                    )
                    .first()
                )
                if existing:
                    existing.projected_assists = projected
                    existing.player_name = player.player_name
                    existing.opponent_team_name = player.opponent_team_name
                    updated += 1
                else:
                    db.add(
                        AssistsProjections(
                            date=today,
                            player_id=player.player_id,
                            player_name=player.player_name,
                            opponent_team_name=player.opponent_team_name,
                            projected_assists=projected,
                        )
                    )
                    created += 1
                db.commit()

                logger.info("%s -> %.2f ast", player.player_name, projected)
            except Exception:
                logger.exception(
                    "generate_%s_predictions: failed for %s",
                    STAT,
                    player.player_name,
                )
                db.rollback()
                errors += 1
                continue

        return {
            "status": "ok",
            "date": today.isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "players_considered": len(active),
            "created": created,
            "updated": updated,
            "skipped_injured": skipped_injured,
            "skipped_insufficient_data": skipped_insufficient,
            "errors": errors,
        }
    finally:
        db.close()
