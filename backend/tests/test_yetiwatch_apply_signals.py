"""Tests for YetiWatch signal application to expected minutes."""

from app.services.etl.wnba.yetiwatch.apply_signals import adjusted_expected_minutes
from app.services.etl.wnba.yetiwatch.models import (
    Corroboration,
    YetiWatchSignalPayload,
)


def _minimal_payload(**overrides):
    base = {
        "run_id": "r1",
        "as_of": "2026-06-28T12:00:00Z",
        "player_id": "1",
        "game_id": "g1",
        "status": "available",
        "impact": {
            "direction": "neutral",
            "magnitude": "low",
            "confidence": 0.5,
        },
        "news_string": "No material news. [neutral] 8:00a ET",
        "provenance": {"source_count": 0, "corroboration": "single"},
    }
    base.update(overrides)
    return YetiWatchSignalPayload.model_validate(base)


def test_minutes_cap_applied():
    payload = _minimal_payload(
        minutes_outlook={"cap_min": 22, "delta_min": None, "note": None},
    )
    assert adjusted_expected_minutes(30.0, payload) == 22.0


def test_out_status_zeroes_minutes():
    payload = _minimal_payload(status="out")
    assert adjusted_expected_minutes(28.0, payload) == 0.0
