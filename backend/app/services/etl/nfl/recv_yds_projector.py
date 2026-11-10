"""Upsert lined receiving-yards board rows (soft-anchored)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.models.predictions_models import RecvYdsPredictions
from app.services.etl.nfl.recv_yds_betting import (
    attach_recv_betting,
    match_player_lines,
)


def _as_game_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def upsert_recv_prediction(session, payload: dict[str, Any]) -> RecvYdsPredictions:
    existing = (
        session.query(RecvYdsPredictions)
        .filter_by(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
        )
        .one_or_none()
    )
    if existing is None:
        existing = RecvYdsPredictions(
            season=payload["season"],
            week=payload["week"],
            player_id=payload["player_id"],
            game_date=_as_game_date(payload["game_date"]),
            player_name=payload["player_name"],
            position=payload["position"],
            team_name=payload["team_name"],
            opponent_team_name=payload["opponent_team_name"],
            predicted_receiving_yards=payload["predicted_receiving_yards"],
            prediction_date=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        session.add(existing)
    for key, value in payload.items():
        if key == "game_date":
            setattr(existing, key, _as_game_date(value))
        elif hasattr(existing, key):
            setattr(existing, key, value)
    session.flush()
    return existing


def project_lined_players(
    session,
    feature_rows: list[dict[str, Any]],
    all_lines: dict[str, dict],
    *,
    anchor_alpha: float | None = None,
) -> dict[str, int]:
    stats = {"upserted": 0, "skipped_no_line": 0, "skipped_no_publish": 0}
    for feat in feature_rows:
        lines = match_player_lines(feat["player_name"], all_lines)
        if not lines:
            stats["skipped_no_line"] += 1
            continue
        attached = attach_recv_betting(
            model_yards=float(feat["model_yards"]),
            confidence_score=float(feat["confidence_score"]),
            player_lines=lines,
            anchor_alpha=anchor_alpha,
        )
        if attached is None:
            stats["skipped_no_publish"] += 1
            continue
        payload = {
            "season": feat["season"],
            "week": feat["week"],
            "game_date": feat["game_date"],
            "player_id": feat["player_id"],
            "player_name": feat["player_name"],
            "position": feat["position"],
            "team_name": feat["team_name"],
            "opponent_team_name": feat["opponent_team_name"],
            "features": feat.get("features"),
            "model_version": feat.get("model_version"),
            **attached,
        }
        upsert_recv_prediction(session, payload)
        stats["upserted"] += 1
    return stats
