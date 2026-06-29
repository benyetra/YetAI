"""Apply YetiWatch structured signals to projection inputs."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBATodayActivePlayers, WNBAYetiWatchSignal
from app.services.etl.wnba.yetiwatch.models import (
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
    db: Session, *, game_date: date
) -> dict[int, YetiWatchSignalPayload]:
    rows = (
        db.query(WNBAYetiWatchSignal)
        .filter(WNBAYetiWatchSignal.game_date == game_date)
        .all()
    )
    out: dict[int, YetiWatchSignalPayload] = {}
    for row in rows:
        payload = YetiWatchSignalPayload.model_validate(row.payload_json)
        out[row.player_id] = payload
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
    # Usage bumps correlate with minutes — light coupling for prop scaling.
    if factor != 1.0:
        minutes *= min(max(factor, 0.7), 1.25)

    return max(0.0, round(minutes, 2))


def apply_signals_to_slate(db: Session, *, game_date: date) -> dict:
    signals = load_latest_signals(db, game_date=game_date)
    if not signals:
        return {"status": "ok", "adjusted": 0, "reason": "no_signals"}

    active_rows = (
        db.query(WNBATodayActivePlayers)
        .filter(WNBATodayActivePlayers.game_date == game_date)
        .all()
    )
    adjusted = 0
    for row in active_rows:
        payload = signals.get(row.player_id)
        if not payload:
            continue
        new_minutes = adjusted_expected_minutes(row.expected_minutes, payload)
        if new_minutes is None or new_minutes == row.expected_minutes:
            continue
        row.expected_minutes = new_minutes
        adjusted += 1
    db.commit()
    return {"status": "ok", "adjusted": adjusted, "signal_count": len(signals)}


def news_for_player(db: Session, *, player_id: int, game_date: date) -> str | None:
    row = (
        db.query(WNBAYetiWatchSignal)
        .filter(
            WNBAYetiWatchSignal.player_id == player_id,
            WNBAYetiWatchSignal.game_date == game_date,
        )
        .first()
    )
    if not row:
        return None
    return row.news_string
