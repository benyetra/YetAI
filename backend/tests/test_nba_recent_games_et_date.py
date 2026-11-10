from datetime import date

from app.services.etl.nba.update_recent_games import game_eastern_date

FALLBACK = date(2026, 11, 10)


def _game(start):
    return {"date": {"start": start}}


def test_evening_tipoff_belongs_to_the_eastern_day_before_utc_rolls():
    # Mon 7:00 pm EST == 00:00 UTC Tuesday: still Monday in Eastern time.
    assert game_eastern_date(_game("2026-11-10T00:00:00.000Z"), FALLBACK) == date(
        2026, 11, 9
    )
    # 10:30 pm EST == 03:30 UTC next day.
    assert game_eastern_date(_game("2026-11-10T03:30:00.000Z"), FALLBACK) == date(
        2026, 11, 9
    )


def test_afternoon_tipoff_keeps_its_utc_date():
    # 3:30 pm EST == 20:30 UTC same day.
    assert game_eastern_date(_game("2026-11-08T20:30:00.000Z"), FALLBACK) == date(
        2026, 11, 8
    )


def test_daylight_saving_offset_applies():
    # Oct 28: EDT (UTC-4), so 7:30 pm ET is 23:30 UTC the same day.
    assert game_eastern_date(_game("2026-10-28T23:30:00Z"), FALLBACK) == date(
        2026, 10, 28
    )
    assert game_eastern_date(_game("2026-10-29T03:59:00Z"), FALLBACK) == date(
        2026, 10, 28
    )


def test_missing_or_bad_start_falls_back_to_queried_date():
    assert game_eastern_date({}, FALLBACK) == FALLBACK
    assert game_eastern_date({"date": {}}, FALLBACK) == FALLBACK
    assert game_eastern_date(_game("not-a-date"), FALLBACK) == FALLBACK
