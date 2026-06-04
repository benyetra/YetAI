"""Smoke tests for WNBA totals_projector port.

Mirrors the structure of tests/test_nba_totals_projector.py but exercises the
WNBA module with WNBA-scale data.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.services.etl.wnba.totals_projector as tp


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


def test_wnba_constants_are_league_scaled():
    assert tp.LEAGUE_AVG_PACE == 80.0
    assert tp.LEAGUE_AVG_ORTG == 102.0
    assert tp.LEAGUE_AVG_DRTG == 102.0
    assert tp.LEAGUE_AVG_TOTAL == 164.0
    assert tp.DENVER_ALTITUDE_BONUS == 0.0


def test_star_player_impacts_contain_wnba_stars():
    stars = tp.STAR_PLAYER_IMPACTS
    assert "a'ja wilson" in stars
    assert "caitlin clark" in stars
    assert "breanna stewart" in stars
    # Impacts are scaled to ~60% of NBA values — all under 5.0
    assert all(v <= 5.0 for v in stars.values())


def test_load_team_data_from_offense_defense_stats(mock_db):
    mock_db.query.return_value = _query_chain([(1611661315, "New York Liberty")])
    tp.load_team_data()
    assert tp.TEAM_NAME_TO_ID["new york liberty"] == 1611661315
    assert tp.TEAM_ID_TO_NAME[1611661315] == "New York Liberty"


def test_estimate_game_pace_returns_league_avg_when_inputs_missing():
    assert tp.estimate_game_pace(0, 0) == tp.LEAGUE_AVG_PACE
    assert tp.estimate_game_pace(80, 0) == tp.LEAGUE_AVG_PACE


def test_estimate_game_pace_within_team_pace_range():
    pace = tp.estimate_game_pace(78.0, 82.0)
    # Slight regression toward league mean (80.0).
    assert 78.0 <= pace <= 82.0


def test_points_values_skips_null_and_invalid():
    games = [
        MagicMock(points=12),
        MagicMock(points=None),
        MagicMock(points=18),
        MagicMock(points="bad"),
    ]
    assert tp._points_values(games) == [12.0, 18.0]


def test_calculate_team_form_tolerates_null_points(mock_db):
    tp.TEAM_NAME_TO_ID["minnesota lynx"] = 1611661324
    tp.TEAM_ID_TO_NAME[1611661324] = "Minnesota Lynx"

    roster_row = MagicMock(player_id=99)
    game_rows = [
        MagicMock(points=20, game_date="2026-05-01"),
        MagicMock(points=None, game_date="2026-05-02"),
        MagicMock(points=22, game_date="2026-05-03"),
        MagicMock(points=21, game_date="2026-05-04"),
        MagicMock(points=19, game_date="2026-05-05"),
        MagicMock(points=23, game_date="2026-05-06"),
    ]

    def query_side_effect(model):
        chain = MagicMock()
        if model is tp.WNBATeamRoster:
            chain.filter_by.return_value.all.return_value = [roster_row]
        elif model is tp.WNBARecentGames:
            chain.filter_by.return_value.all.return_value = game_rows
        else:
            chain.distinct.return_value.all.return_value = []
        return chain

    mock_db.query.side_effect = query_side_effect

    form = tp.calculate_team_form("Minnesota Lynx")
    assert isinstance(form, float)
    assert -8.0 <= form <= 8.0
