"""Generate per-player points projections via the XGBoost model.

Port of YetiBets/scripts/nba/points_predictions_v2.py — ML-only path.
FanDuel lines from The Odds API when ``ODDS_API_KEY`` is configured.
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
from app.services.etl.nba._fanduel_lines import (
    PROP_MARKETS,
    apply_fanduel_to_projection,
)
from app.services.etl.nba.prop_calibration import maybe_attach_p_over
from app.services.etl.nba._ml_predict import get_metadata, predict_points
from app.services.ml_model_version import (
    attach_model_version,
    model_version_from_metadata,
)

logger = logging.getLogger(__name__)

INJURY_SKIP_STATUSES = {"out", "ir", "doubtful"}
FD_MARKET = PROP_MARKETS["points"]


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
    lines_attached = 0
    rows_written = 0

    model_version = model_version_from_metadata(get_metadata("points"), prefix="xgb")

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
                "fanduel_lines_attached": 0,
                "fanduel_line_coverage_pct": None,
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
                    row = existing
                    updated += 1
                else:
                    row = PointsProjections(
                        date=today,
                        player_id=player.player_id,
                        player_name=player.player_name,
                        opponent_team_name=player.opponent_team_name,
                        projected_points=projected,
                    )
                    db.add(row)
                    created += 1
                attach_model_version(row, model_version)
                if apply_fanduel_to_projection(
                    row,
                    team_name=player.team_name,
                    opponent_team_name=player.opponent_team_name,
                    player_name=player.player_name,
                    market=FD_MARKET,
                    projection=projected,
                ):
                    lines_attached += 1
                maybe_attach_p_over(
                    row,
                    stat="points",
                    projected=projected,
                    line=getattr(row, "fanduel_line", None),
                )
                rows_written += 1
                db.commit()

                logger.info("%s -> %.2f pts", player.player_name, projected)
            except Exception:
                logger.exception(
                    "generate_points_predictions: failed for %s", player.player_name
                )
                db.rollback()
                errors += 1
                continue

        coverage = (
            round(100.0 * lines_attached / rows_written, 1) if rows_written else None
        )
        logger.info(
            "generate_points_predictions: fanduel_line coverage %s%% (%s/%s)",
            coverage,
            lines_attached,
            rows_written,
        )
        return {
            "status": "ok",
            "date": today.isoformat(),
            "model_version": model_version,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "players_considered": len(active),
            "created": created,
            "updated": updated,
            "skipped_injured": skipped_injured,
            "skipped_insufficient_data": skipped_insufficient,
            "errors": errors,
            "fanduel_lines_attached": lines_attached,
            "fanduel_line_coverage_pct": coverage,
        }
    finally:
        db.close()
