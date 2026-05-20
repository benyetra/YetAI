"""Unit tests for NBA totals_projector DB helpers (Session API, not Flask db.session)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

import app.services.etl.nba.totals_projector as tp


@pytest.fixture(autouse=True)
def reset_team_maps():
    tp.TEAM_NAME_TO_ID.clear()
    tp.TEAM_ID_TO_NAME.clear()
    yield
    tp.TEAM_NAME_TO_ID.clear()
    tp.TEAM_ID_TO_NAME.clear()


@pytest.fixture
def mock_db():
    db = MagicMock(name="Session")
    tp.db = db
    yield db
    tp.db = None


def _query_chain(rows):
    chain = MagicMock()
    chain.distinct.return_value.all.return_value = rows
    return chain


def test_load_team_data_from_offense_defense_stats(mock_db):
    mock_db.query.return_value = _query_chain([(10, "New York Knicks")])

    tp.load_team_data()

    assert tp.TEAM_NAME_TO_ID["new york knicks"] == 10
    assert tp.TEAM_ID_TO_NAME[10] == "New York Knicks"
    assert mock_db.query.called


def test_load_team_data_falls_back_to_today_active_players(mock_db):
    mock_db.query.side_effect = [
        _query_chain([]),
        _query_chain([]),
        _query_chain([(5, "Boston Celtics")]),
    ]

    tp.load_team_data()

    assert tp.TEAM_NAME_TO_ID["boston celtics"] == 5
    assert mock_db.query.call_count == 3


def test_load_team_data_cached(mock_db):
    tp.TEAM_NAME_TO_ID["lakers"] = 1
    tp.TEAM_ID_TO_NAME[1] = "Lakers"

    tp.load_team_data()

    mock_db.query.assert_not_called()


def _sample_projection() -> dict:
    return {
        "game_date": date(2026, 5, 19),
        "home_team": "New York Knicks",
        "away_team": "Cleveland Cavaliers",
        "projected_total": 218.5,
        "home_projected_score": 110.0,
        "away_projected_score": 108.5,
        "base_projection": 217.0,
        "expected_pace": 99.0,
        "home_offensive_rating": 115.0,
        "away_offensive_rating": 114.0,
        "home_defensive_rating": 112.0,
        "away_defensive_rating": 113.0,
        "injury_adjustment": -1.0,
        "rest_adjustment": 0.0,
        "venue_adjustment": 0.5,
        "form_adjustment": 0.2,
        "total_adjustment": -0.3,
        "market_total": 220.5,
        "edge": -2.0,
        "recommendation": "UNDER",
        "confidence_score": 0.65,
        "injury_report": "{}",
        "factors": "{}",
        "home_starters": None,
        "away_starters": None,
    }


def test_save_projection_inserts_via_session_api(mock_db):
    tp.TEAM_NAME_TO_ID["new york knicks"] = 1
    tp.TEAM_NAME_TO_ID["cleveland cavaliers"] = 2
    tp.TEAM_ID_TO_NAME[1] = "New York Knicks"
    tp.TEAM_ID_TO_NAME[2] = "Cleveland Cavaliers"

    mock_db.query.return_value.filter_by.return_value.first.return_value = None

    tp.save_projection(_sample_projection())

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.rollback.assert_not_called()


def test_save_projection_updates_existing_row(mock_db):
    existing = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = existing

    tp.save_projection(_sample_projection())

    mock_db.add.assert_not_called()
    assert existing.projected_total == 218.5
    assert existing.recommendation == "UNDER"
    mock_db.commit.assert_called_once()


def test_save_projection_rollback_on_error(mock_db):
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    mock_db.commit.side_effect = RuntimeError("db down")

    tp.save_projection(_sample_projection())

    mock_db.rollback.assert_called_once()
