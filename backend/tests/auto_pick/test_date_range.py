"""Auto-pick "today" is the US Eastern slate day, not the UTC calendar day."""

from datetime import date, datetime

from app.services.auto_pick.candidate import slate_window


def test_late_evening_et_stays_on_same_slate_day():
    # 02:00 UTC May 25 == 22:00 ET May 24 (EDT)
    dr = slate_window(datetime(2026, 5, 25, 2, 0))
    assert dr.slate_date == date(2026, 5, 24)
    assert dr.start == datetime(2026, 5, 24, 4, 0)  # midnight ET in UTC
    assert dr.end == datetime(2026, 5, 25, 4, 0)


def test_window_includes_late_west_coast_game():
    dr = slate_window(datetime(2026, 5, 24, 15, 0))
    late_game = datetime(2026, 5, 25, 2, 10)  # 10:10 PM ET
    assert dr.start <= late_game < dr.end
