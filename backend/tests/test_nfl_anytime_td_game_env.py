"""Tests for anytime-TD game-env / lines matching (offline)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.etl.nfl.anytime_td_features import (
    game_env_from_line,
    index_game_lines_by_team_for_week,
    merge_weather_into_matchup,
)
from app.services.etl.nfl.update_game_lines import (
    GAME_LINES_HORIZON_DAYS,
    game_date_in_refresh_window,
)


def test_game_lines_horizon_covers_full_week_slate():
    assert GAME_LINES_HORIZON_DAYS >= 10
    today = date(2026, 9, 9)  # Wed
    assert game_date_in_refresh_window(date(2026, 9, 9), today=today)
    assert game_date_in_refresh_window(date(2026, 9, 14), today=today)  # Sun
    assert game_date_in_refresh_window(date(2026, 9, 15), today=today)  # Mon
    assert not game_date_in_refresh_window(date(2026, 9, 25), today=today)


def test_game_env_from_line_computes_implied_totals():
    line = SimpleNamespace(total=47.0, spread_home=-3.0)
    home = game_env_from_line(line, home=True)
    away = game_env_from_line(line, home=False)
    assert home["implied_total"] == 47.0
    assert home["spread"] == -3.0
    assert abs(home["implied_team_total"] - 25.0) < 1e-9
    assert abs(away["implied_team_total"] - 22.0) < 1e-9
    assert away["spread"] == 3.0


def test_load_game_lines_filters_to_schedule_dates():
    lines = [
        SimpleNamespace(
            game_date=date(2026, 9, 14),
            home_team_name="Kansas City Chiefs",
            away_team_name="Buffalo Bills",
            total=48.5,
            spread_home=-2.5,
        ),
        SimpleNamespace(
            game_date=date(2026, 9, 7),
            home_team_name="Kansas City Chiefs",
            away_team_name="Baltimore Ravens",
            total=44.0,
            spread_home=-6.0,
        ),
    ]
    schedules = [
        {
            "week": 2,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "gameday": "2026-09-14",
            "roof": "outdoors",
            "wind": 12,
        }
    ]
    by_team = index_game_lines_by_team_for_week(
        lines,
        schedule_records=schedules,
        week=2,
    )

    assert "KC" in by_team
    assert abs(by_team["KC"]["implied_total"] - 48.5) < 1e-9
    # Week-1 line must not win
    assert by_team["KC"]["implied_total"] != 44.0


def test_merge_weather_prefers_forecast_precip_and_wind():
    match = {
        "outdoor": True,
        "wind_mph": 5.0,
        "precip": False,
        "game_date": date(2026, 9, 14),
    }
    merged = merge_weather_into_matchup(
        match,
        {
            "wind_mph": 18.0,
            "precip": True,
            "precip_probability": 0.7,
            "temperature": 48.0,
        },
    )
    assert merged["wind_mph"] == 18.0
    assert merged["precip"] is True
    assert merged["temperature"] == 48.0
