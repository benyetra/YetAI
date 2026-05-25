"""Tests for NHL season config and DB-backed league defaults."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nhl import _config as nhl_config


def test_get_nhl_season_default(monkeypatch):
    monkeypatch.delenv("NHL_SEASON", raising=False)
    assert nhl_config.get_nhl_season() == nhl_config.DEFAULT_NHL_SEASON


def test_get_nhl_season_from_env(monkeypatch):
    monkeypatch.setenv("NHL_SEASON", "20262027")
    assert nhl_config.get_nhl_season() == 20262027


def test_get_nhl_season_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("NHL_SEASON", "not-a-season")
    assert nhl_config.get_nhl_season() == nhl_config.DEFAULT_NHL_SEASON


@patch("app.services.etl.nhl._config.db_session")
def test_team_stat_or_default_uses_row(mock_db):
    mock_db.query.return_value.filter_by.return_value.first.return_value = (
        SimpleNamespace(shots_against_per_game=32.5)
    )
    assert nhl_config.team_stat_or_default(10, "shots_against_per_game", 30.0) == 32.5


@patch("app.services.etl.nhl._config.db_session")
def test_team_stat_or_default_missing_row(mock_db):
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    assert nhl_config.team_stat_or_default(10, "shots_against_per_game", 30.0) == 30.0


@patch("app.services.etl.nhl._config.db_session")
def test_league_average_from_db(mock_db):
    mock_db.query.return_value.filter.return_value.all.return_value = [
        (28.0,),
        (32.0,),
    ]
    assert nhl_config.get_league_avg_shots_against() == pytest.approx(30.0)


@patch("app.services.etl.nhl._config.db_session")
def test_league_average_empty_db_uses_fallback(mock_db):
    mock_db.query.return_value.filter.return_value.all.return_value = []
    assert nhl_config.get_league_avg_shots_against() == nhl_config.DEFAULT_SHOTS_AGAINST
    assert nhl_config.get_league_avg_shooting_pct() == nhl_config.DEFAULT_SHOOTING_PCT


def test_resolve_season_none_uses_config(monkeypatch):
    monkeypatch.setenv("NHL_SEASON", "20242025")
    assert nhl_config._resolve_season(None) == 20242025
    assert nhl_config._resolve_season(20232024) == 20232024
