"""Generate per-player points projections via the XGBoost model.

Port of YetiBets/scripts/nba/points_predictions_v2.py — but stripped down to
the ML-only path. The original v2 script ran an ensemble of a rule-based
weighted projection + XGBoost; here we trust the model directly since the
metadata reports `test_mae ~5.0` and the ensemble blend added complexity
without measurable gains in YetiBets's recent runs.

Flow:
  1. Query pred_today_active_players for today's date (Eastern).
  2. For each active player:
     - skip if marked out/ir/doubtful in pred_player_injury_status
     - build the 44-feature vector via _feature_engineering.build_points_features
     - skip if insufficient history (<5 games)
     - run _ml_predict.predict_points(features) -> projection
     - clamp negative predictions to 0 (XGBoost can dip below for low-volume bench)
     - upsert into pred_points_projections
  3. Return a JSON-able summary dict.

fanduel_line/fanduel_over_under are intentionally left NULL — no FanDuel feed
is wired up yet on the YetAI side (Development-flm tracks this).
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import (
    PlayerInjuryStatus,
    PointsProjections,
    TodayActivePlayers,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._feature_engineering import build_points_features
from app.services.etl.nba._ml_predict import predict_points

logger = logging.getLogger(__name__)

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
            logger.info("generate_points_predictions: no active players for %s", today)
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
                    logger.info(
                        "Skipping %s (injury: %s)", player.player_name, injury_status
                    )
                    skipped_injured += 1
                    continue

                features = build_points_features(
                    db=db,
                    player_id=player.player_id,
                    game_date=today,
                    opponent_team_id=player.opponent_team_id,
                )
                if features is None:
                    logger.info(
                        "Skipping %s (insufficient game history)", player.player_name
                    )
                    skipped_insufficient += 1
                    continue

                prediction = predict_points(features)
                # XGBoost can occasionally output slightly negative values for
                # very-low-volume bench profiles. The actual stat can't be
                # negative, so floor at 0.
                projected = max(0.0, round(prediction, 2))

                existing = (
                    db.query(PointsProjections)
                    .filter(
                        PointsProjections.date == today,
                        PointsProjections.player_id == player.player_id,
                    )
                    .first()
                )
                if existing:
                    existing.projected_points = projected
                    existing.player_name = player.player_name
                    existing.opponent_team_name = player.opponent_team_name
                    existing.fanduel_line = None
                    existing.fanduel_over_under = None
                    updated += 1
                else:
                    db.add(
                        PointsProjections(
                            date=today,
                            player_id=player.player_id,
                            player_name=player.player_name,
                            opponent_team_name=player.opponent_team_name,
                            projected_points=projected,
                            fanduel_line=None,
                            fanduel_over_under=None,
                        )
                    )
                    created += 1
                db.commit()

                logger.info("%s -> %.2f pts", player.player_name, projected)
            except Exception:
                logger.exception(
                    "generate_points_predictions: failed for %s", player.player_name
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
