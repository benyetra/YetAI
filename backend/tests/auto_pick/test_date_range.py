"""Regression: auto-pick date window must include the full UTC calendar day."""

from datetime import datetime

from app.services.auto_pick.orchestrator import date_range_for_utc_day


def test_date_range_for_utc_day_uses_midnight_not_afternoon():
    now = datetime(2026, 5, 24, 14, 32, 50)
    dr = date_range_for_utc_day(now)
    assert dr.start.hour == 0 and dr.start.minute == 0
    assert dr.start.date() == now.date()
    assert dr.end.date() == now.date()
    assert dr.start < now
