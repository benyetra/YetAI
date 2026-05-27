"""Unit tests for cross-league accuracy overview window bounds."""

from __future__ import annotations

from datetime import date

from app.services.accuracy_overview_service import window_date_bounds


def test_window_last_30():
    start, end = window_date_bounds(sport="mlb", mode="last_30", today=date(2026, 6, 1))
    assert end == date(2026, 6, 1)
    assert start == date(2026, 5, 2)


def test_window_mlb_before_opener_rolls_year():
    start, end = window_date_bounds(sport="mlb", mode="season", today=date(2026, 3, 10))
    assert end == date(2026, 3, 10)
    assert start == date(2025, 3, 15)


def test_window_mlb_after_opener_current_year():
    start, end = window_date_bounds(sport="mlb", mode="season", today=date(2026, 7, 1))
    assert start == date(2026, 3, 15)
    assert end == date(2026, 7, 1)


def test_window_nba_before_season_start():
    start, end = window_date_bounds(sport="nba", mode="season", today=date(2026, 9, 15))
    assert start == date(2025, 10, 1)
    assert end == date(2026, 9, 15)


def test_window_wnba():
    start, end = window_date_bounds(sport="wnba", mode="season", today=date(2026, 6, 1))
    assert start == date(2026, 5, 1)
    assert end == date(2026, 6, 1)
