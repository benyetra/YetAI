from datetime import date

from app.services.etl.grading_window import grading_dates


def test_default_window_is_last_three_days_ending_yesterday(monkeypatch):
    monkeypatch.delenv("NHL_GRADING_LOOKBACK_DAYS", raising=False)
    assert grading_dates("nhl", today=date(2026, 11, 13)) == [
        date(2026, 11, 10),
        date(2026, 11, 11),
        date(2026, 11, 12),
    ]


def test_env_override_and_bad_value(monkeypatch):
    monkeypatch.setenv("NHL_GRADING_LOOKBACK_DAYS", "1")
    assert grading_dates("nhl", today=date(2026, 11, 13)) == [date(2026, 11, 12)]
    monkeypatch.setenv("NHL_GRADING_LOOKBACK_DAYS", "x")
    assert len(grading_dates("nhl", today=date(2026, 11, 13))) == 3
