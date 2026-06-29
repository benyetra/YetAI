"""Apply YetiWatch structured signals to basketball projection inputs."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    PlayerExpectedMinutes,
    TodayActivePlayers,
    WNBATodayActivePlayers,
    YetiWatchSignal,
)
from app.services.etl.yetiwatch.models import (
    PlayerStatus,
    UsageDelta,
    YetiWatchSignalPayload,
)

logger = logging.getLogger(__name__)

_USAGE_FACTOR = {
    UsageDelta.STRONG_DECREASE: 0.85,
    UsageDelta.DECREASE: 0.93,
    UsageDelta.NEUTRAL: 1.0,
    UsageDelta.INCREASE: 1.08,
    UsageDelta.STRONG_INCREASE: 1.15,
}


def load_latest_signals(
    db: Session, *, sport: str, game_date: date
) -> dict[str, YetiWatchSignalPayload]:
    rows = (
        db.query(YetiWatchSignal)
        .filter(
            YetiWatchSignal.sport == sport,
            YetiWatchSignal.game_date == game_date,
        )
        .all()
    )
    out: dict[str, YetiWatchSignalPayload] = {}
    for row in rows:
        payload = YetiWatchSignalPayload.model_validate(row.payload_json)
        out[row.entity_id] = payload
    return out


def adjusted_expected_minutes(
    baseline: float | None,
    payload: YetiWatchSignalPayload | None,
) -> float | None:
    if baseline is None:
        return None
    if payload is None:
        return baseline

    minutes = baseline
    outlook = payload.minutes_outlook
    if outlook:
        if outlook.cap_min is not None:
            minutes = min(minutes, float(outlook.cap_min))
        if outlook.delta_min is not None:
            minutes = minutes + float(outlook.delta_min)

    if payload.status == PlayerStatus.OUT:
        return 0.0
    if payload.status == PlayerStatus.DOUBTFUL:
        minutes *= 0.5

    factor = _USAGE_FACTOR.get(payload.usage_delta, 1.0)
    if payload.usage_delta_factor is not None:
        factor = payload.usage_delta_factor
    if factor != 1.0:
        minutes *= min(max(factor, 0.7), 1.25)

    return max(0.0, round(minutes, 2))


def apply_signals_to_nba_slate(db: Session, *, game_date: date) -> dict:
    signals = load_latest_signals(db, sport="nba", game_date=game_date)
    if not signals:
        return {"status": "ok", "adjusted": 0, "reason": "no_signals"}

    active_rows = (
        db.query(TodayActivePlayers)
        .filter(TodayActivePlayers.game_date == game_date)
        .all()
    )
    minutes_rows = {row.player_id: row for row in db.query(PlayerExpectedMinutes).all()}
    adjusted = 0
    for row in active_rows:
        payload = signals.get(str(row.player_id))
        if not payload:
            continue
        minutes_row = minutes_rows.get(row.player_id)
        if not minutes_row:
            continue
        new_minutes = adjusted_expected_minutes(
            minutes_row.expected_minutes_today, payload
        )
        if new_minutes is None or new_minutes == minutes_row.expected_minutes_today:
            continue
        minutes_row.expected_minutes_today = new_minutes
        adjusted += 1
    db.commit()
    return {"status": "ok", "adjusted": adjusted, "signal_count": len(signals)}


def apply_signals_to_wnba_slate(db: Session, *, game_date: date) -> dict:
    signals = load_latest_signals(db, sport="wnba", game_date=game_date)
    if not signals:
        return {"status": "ok", "adjusted": 0, "reason": "no_signals"}

    active_rows = (
        db.query(WNBATodayActivePlayers)
        .filter(WNBATodayActivePlayers.game_date == game_date)
        .all()
    )
    adjusted = 0
    for row in active_rows:
        payload = signals.get(str(row.player_id))
        if not payload:
            continue
        new_minutes = adjusted_expected_minutes(row.expected_minutes, payload)
        if new_minutes is None or new_minutes == row.expected_minutes:
            continue
        row.expected_minutes = new_minutes
        adjusted += 1
    db.commit()
    return {"status": "ok", "adjusted": adjusted, "signal_count": len(signals)}


def news_for_entity(
    db: Session, *, sport: str, entity_id: str | int, game_date: date
) -> str | None:
    row = (
        db.query(YetiWatchSignal)
        .filter(
            YetiWatchSignal.sport == sport,
            YetiWatchSignal.entity_id == str(entity_id),
            YetiWatchSignal.game_date == game_date,
        )
        .first()
    )
    if not row:
        return None
    return row.news_string
