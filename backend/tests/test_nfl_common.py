"""Tests for NFL season/week helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from app.services.etl.nfl import nfl_common


def test_get_nfl_season_default(monkeypatch):
    monkeypatch.delenv("NFL_SEASON", raising=False)
    assert nfl_common.get_nfl_season() == 2026
    assert nfl_common.DEFAULT_NFL_SEASON == 2026


def test_get_nfl_season_from_env(monkeypatch):
    monkeypatch.setenv("NFL_SEASON", "2026")
    assert nfl_common.get_nfl_season() == 2026


def test_get_nfl_season_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("NFL_SEASON", "bad")
    assert nfl_common.get_nfl_season() == nfl_common.DEFAULT_NFL_SEASON


def test_resolve_nfl_season_explicit():
    assert nfl_common.resolve_nfl_season(2024) == 2024


@patch("app.services.etl.nfl.nfl_common.get_nfl_season", return_value=2025)
def test_week_before_season_start_is_week_one(_mock_season):
    # 2025 season first Thursday after Labor Day is 2025-09-04
    assert nfl_common.get_current_nfl_week(season=2025, today=date(2025, 9, 3)) == 1


@patch("app.services.etl.nfl.nfl_common.get_nfl_season", return_value=2025)
def test_week_increases_after_kickoff(_mock_season):
    assert nfl_common.get_current_nfl_week(season=2025, today=date(2025, 9, 11)) == 2


@patch("app.services.etl.nfl.nfl_common.get_nfl_season", return_value=2025)
def test_week_capped_at_eighteen(_mock_season):
    assert nfl_common.get_current_nfl_week(season=2025, today=date(2026, 1, 15)) == 18


def test_week_before_2026_kickoff_is_week_one():
    # 2026 Labor Day is Mon Sep 7 → first Thursday Sep 10
    assert nfl_common.get_current_nfl_week(season=2026, today=date(2026, 8, 10)) == 1
    assert nfl_common.get_current_nfl_week(season=2026, today=date(2026, 9, 9)) == 1


def test_week_after_2026_kickoff():
    assert nfl_common.get_current_nfl_week(season=2026, today=date(2026, 9, 17)) == 2
