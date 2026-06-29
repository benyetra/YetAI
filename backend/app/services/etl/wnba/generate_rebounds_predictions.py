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
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba._feature_engineering import (
    apply_expected_minutes,
    build_features,
)
from app.services.etl.wnba._ml_predict import predict
from app.services.etl.wnba._prop_lines import (
    attach_prop_market_fields,
    resolve_wnba_event_id,
)
from app.services.etl.wnba._yetiwatch_news import attach_yetiwatch_news

logger = logging.getLogger(__name__)

INJURY_SKIP = {"out", "ir", "doubtful"}
STAT = "rebounds"


def run() -> dict:
    today = now_eastern().date()
    db = SessionLocal()
    upsert_rows: list[dict] = []
    skipped_injured = 0
    skipped_thin = 0
    lines_attached = 0
    event_ids: dict[tuple[str, str], str | None] = {}
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
                db,
                stat_col=STAT,
                player_id=p.player_id,
                game_date=today,
                opponent_team_id=p.opponent_team_id,
            )
            if feats is None:
                skipped_thin += 1
                continue
            feats = apply_expected_minutes(feats, p.expected_minutes)
            try:
                projected = predict(STAT, feats)
            except Exception as exc:
                logger.warning("predict failed for player %s: %s", p.player_id, exc)
                continue
            row = {
                "date": today,
                "player_id": p.player_id,
                "player_name": p.player_name,
                "opponent_team_name": p.opponent_team_name,
                "projected_rebounds": projected,
                "market_line": None,
                "edge": None,
                "recommendation": "NO_PLAY",
                "confidence_score": None,
                "created_at": datetime.utcnow(),
            }
            matchup = (p.team_name, p.opponent_team_name or "")
            if matchup not in event_ids:
                event_ids[matchup] = resolve_wnba_event_id(
                    db, today, matchup[0], matchup[1]
                )
            if attach_prop_market_fields(
                row,
                db=db,
                game_date=today,
                team_name=p.team_name,
                opponent_team_name=p.opponent_team_name or "",
                player_name=p.player_name,
                stat=STAT,
                projected=projected,
                event_id=event_ids[matchup],
            ):
                lines_attached += 1
            attach_yetiwatch_news(row, db=db, player_id=p.player_id, game_date=today)
            upsert_rows.append(row)
        upsert_many(
            db,
            WNBAReboundsProjections,
            upsert_rows,
            conflict_keys=["player_id", "date"],
        )
        db.commit()
        rows_written = len(upsert_rows)
        coverage = (
            round(100.0 * lines_attached / rows_written, 1) if rows_written else None
        )
        return {
            "status": "ok",
            "date": today.isoformat(),
            "projections_written": rows_written,
            "market_lines_attached": lines_attached,
            "market_line_coverage_pct": coverage,
            "skipped_injured": skipped_injured,
            "skipped_thin_history": skipped_thin,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
