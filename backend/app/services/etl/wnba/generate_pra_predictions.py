"""WNBA PRA (points + rebounds + assists) combo projections.

Derived from component projections (no separate XGB). Mirrors NBA
``generate_pra_predictions`` with WNBA floors / tables.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAAssistsProjections,
    WNBAPlayerInjuryStatus,
    WNBAPointsProjections,
    WNBAPRAProjections,
    WNBARecentGames,
    WNBAReboundsProjections,
    WNBATodayActivePlayers,
)
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba._prop_lines import (
    attach_prop_market_fields,
    resolve_wnba_event_id,
)
from app.services.etl.wnba._yetiwatch_news import attach_yetiwatch_news

logger = logging.getLogger(__name__)

INJURY_SKIP = {"out", "ir", "doubtful"}
CORRELATION_ADJUSTMENT = 0.98
MIN_PRA = 12.0
MIN_AVG_MINUTES = 15.0
STAT = "pra"


def _weighted_stat(recent_games: list, attr: str, min_games: int = 5) -> float | None:
    values = []
    for g in recent_games[:10]:
        val = getattr(g, attr, None)
        if val is not None and val >= 0:
            values.append(float(val))
    if len(values) < min_games:
        return None
    if len(values) >= 5:
        weights = [0.25, 0.20, 0.18, 0.15, 0.12, 0.05, 0.03, 0.01, 0.005, 0.005]
        weights = weights[: len(values)]
        weight_sum = sum(weights)
        weights = [w / weight_sum for w in weights]
        return sum(v * w for v, w in zip(values, weights))
    return sum(values) / len(values)


def _get_component(
    db,
    model,
    field: str,
    player_id: int,
    game_date,
    recent_games: list,
    recent_attr: str,
) -> float | None:
    row = (
        db.query(model)
        .filter(model.player_id == player_id, model.date == game_date)
        .first()
    )
    if row:
        val = getattr(row, field, None)
        if val is not None:
            return float(val)
    return _weighted_stat(recent_games, recent_attr)


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

            recent = (
                db.query(WNBARecentGames)
                .filter(
                    WNBARecentGames.player_id == p.player_id,
                    WNBARecentGames.minutes.isnot(None),
                    WNBARecentGames.minutes > 0,
                )
                .order_by(WNBARecentGames.game_date.desc())
                .limit(10)
                .all()
            )
            if len(recent) < 5:
                skipped_thin += 1
                continue
            avg_min = sum(float(g.minutes) for g in recent[:5]) / min(5, len(recent))
            if avg_min < MIN_AVG_MINUTES:
                skipped_thin += 1
                continue

            points = _get_component(
                db,
                WNBAPointsProjections,
                "projected_points",
                p.player_id,
                today,
                recent,
                "points",
            )
            rebounds = _get_component(
                db,
                WNBAReboundsProjections,
                "projected_rebounds",
                p.player_id,
                today,
                recent,
                "rebounds",
            )
            assists = _get_component(
                db,
                WNBAAssistsProjections,
                "projected_assists",
                p.player_id,
                today,
                recent,
                "assists",
            )
            if None in (points, rebounds, assists):
                skipped_thin += 1
                continue

            projected = max(
                MIN_PRA,
                min((points + rebounds + assists) * CORRELATION_ADJUSTMENT, 55.0),
            )
            if projected < MIN_PRA:
                skipped_thin += 1
                continue

            row = {
                "date": today,
                "player_id": p.player_id,
                "player_name": p.player_name,
                "opponent_team_name": p.opponent_team_name,
                "projected_pra": round(projected, 1),
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
            WNBAPRAProjections,
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
