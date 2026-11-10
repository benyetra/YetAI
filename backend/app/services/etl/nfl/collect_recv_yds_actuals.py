"""Grade receiving yards actuals into pred_recv_yds_actuals."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def grade_recv_row(
    *,
    actual_yards: float,
    predicted: float | None,
    ou_line: float | None,
) -> dict[str, Any]:
    err = None if predicted is None else float(actual_yards) - float(predicted)
    hit = None if ou_line is None else float(actual_yards) > float(ou_line)
    return {
        "actual_receiving_yards": float(actual_yards),
        "prediction_error": err,
        "hit_over_under": hit,
    }


def upsert_recv_actual(session, payload: dict[str, Any]):
    from app.models.predictions_models import RecvYdsActuals

    existing = (
        session.query(RecvYdsActuals)
        .filter_by(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
        )
        .one_or_none()
    )
    if existing is None:
        existing = RecvYdsActuals(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
            game_date=payload["game_date"],
            player_name=payload["player_name"],
            position=payload["position"],
            team_name=payload["team_name"],
            opponent_team_name=payload["opponent_team_name"],
            actual_receiving_yards=payload["actual_receiving_yards"],
            data_collection_date=datetime.utcnow(),
        )
        session.add(existing)
    for key, value in payload.items():
        if hasattr(existing, key):
            setattr(existing, key, value)
    return existing


def collect_for_week(
    session, *, season: int, week: int, weekly_stats: list[dict]
) -> int:
    """Match prediction rows to weekly receiving yards and upsert actuals."""
    from app.models.predictions_models import RecvYdsPredictions

    preds = session.query(RecvYdsPredictions).filter_by(season=season, week=week).all()
    by_id = {str(r.get("player_id")): r for r in weekly_stats}
    upserted = 0
    for pred in preds:
        stat = by_id.get(str(pred.player_id))
        if not stat or stat.get("receiving_yards") is None:
            continue
        graded = grade_recv_row(
            actual_yards=float(stat["receiving_yards"]),
            predicted=pred.predicted_receiving_yards,
            ou_line=pred.ou_line,
        )
        upsert_recv_actual(
            session,
            {
                "season": season,
                "week": week,
                "game_date": pred.game_date,
                "player_id": pred.player_id,
                "player_name": pred.player_name,
                "position": pred.position,
                "team_name": pred.team_name,
                "opponent_team_name": pred.opponent_team_name,
                "actual_receptions": stat.get("receptions"),
                "actual_targets": stat.get("targets"),
                "predicted_receiving_yards": pred.predicted_receiving_yards,
                "ou_line": pred.ou_line,
                "prediction_method": pred.prediction_method,
                **graded,
            },
        )
        upserted += 1
    return upserted


def run() -> dict:
    from app.services.etl.nfl._db import close_session, db_session, init_session
    from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
    from app.services.etl.nfl.recv_yds_usage import load_weekly_receiver_rows

    init_session()
    try:
        season = int(get_nfl_season())
        # Grade the previous completed week by default (mirror QB actuals cadence).
        week = max(1, int(get_current_nfl_week()) - 1)
        weekly = [
            r
            for r in load_weekly_receiver_rows(season)
            if int(r.get("week") or 0) == week
        ]
        n = collect_for_week(
            db_session(), season=season, week=week, weekly_stats=weekly
        )
        db_session().commit()
        return {
            "status": "ok",
            "task": "nfl_collect_recv_yds_actuals",
            "upserted": n,
            "season": season,
            "week": week,
        }
    finally:
        close_session()
