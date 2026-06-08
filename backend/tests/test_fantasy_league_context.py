"""Tests for fantasy season / trade-deadline context."""

from datetime import date

from app.services.fantasy_league_context import build_season_context


def test_build_season_context_uses_real_nfl_week():
    ctx = build_season_context(season=2025, today=date(2025, 9, 11))
    assert ctx["current_week"] == 2
    assert ctx["trade_deadline_weeks"] == 8
    assert ctx["trade_deadline_passed"] is False


def test_build_season_context_dynasty_has_no_deadline():
    ctx = build_season_context(season=2025, is_dynasty=True, today=date(2025, 9, 11))
    assert ctx["trade_deadline_weeks"] is None
    assert ctx["trade_deadline_passed"] is False


def test_build_season_context_after_deadline():
    ctx = build_season_context(season=2025, today=date(2025, 11, 15))
    assert ctx["current_week"] >= 11
    assert ctx["trade_deadline_passed"] is True
    assert ctx["trade_deadline_weeks"] == 0
