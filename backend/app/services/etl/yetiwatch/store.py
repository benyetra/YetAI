"""Persist YetiWatch signals to pred_yetiwatch_signals."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.predictions_models import YetiWatchSignal
from app.services.etl.wnba._db_upsert import upsert_many


def upsert_signals(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    return upsert_many(
        session,
        YetiWatchSignal,
        rows,
        conflict_keys=["sport", "entity_id", "game_date"],
    )
