from datetime import date

from scripts.nba_recent_games_date_repair import (
    backup_table,
    season_window,
    utc_days_to_refetch,
)

TODAY = date(2026, 11, 10)


def test_current_season_window_runs_from_opening_night_to_today():
    assert season_window(2026, TODAY) == (date(2026, 10, 20), TODAY)


def test_finished_season_window_ends_june_30():
    assert season_window(2025, TODAY) == (date(2025, 10, 21), date(2026, 6, 30))


def test_refetch_reaches_one_utc_day_past_the_window_but_not_past_today():
    days = utc_days_to_refetch(date(2026, 11, 8), date(2026, 11, 9), TODAY)
    assert days == [date(2026, 11, 8), date(2026, 11, 9), date(2026, 11, 10)]
    clipped = utc_days_to_refetch(date(2026, 11, 8), TODAY, TODAY)
    assert clipped[-1] == TODAY


def test_backup_table_is_per_season():
    assert backup_table(2025) == "pred_recent_games_bak_2025"
