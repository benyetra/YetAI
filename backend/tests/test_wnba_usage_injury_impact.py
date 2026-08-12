"""Tests for WNBA usage-weighted totals injury impact."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

import app.services.etl.wnba.totals_projector as tp
from app.models.predictions_models import (
    WNBAPlayerInjuryStatus,
    WNBATeamRoster,
)


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


def _game(minutes: float, points: float, usage: float | None):
    g = MagicMock()
    g.minutes = minutes
    g.points = points
    g.usage_percentage = usage
    g.game_date = date(2026, 6, 1)
    return g


def test_estimate_player_totals_impact_scales_with_usage():
    high_usg = [_game(32, 10, 32.0) for _ in range(8)]
    low_usg = [_game(32, 10, 18.0) for _ in range(8)]
    high = tp.estimate_player_totals_impact_from_games(high_usg)
    low = tp.estimate_player_totals_impact_from_games(low_usg)
    assert high is not None and low is not None
    assert high > low
    assert high < tp.INJURY_MAX_PLAYER_IMPACT
    assert low < tp.INJURY_MAX_PLAYER_IMPACT


def test_estimate_skips_bench_minutes():
    bench = [_game(8, 3, 10.0) for _ in range(8)]
    assert tp.estimate_player_totals_impact_from_games(bench) is None


def test_calculate_injury_impact_uses_usage_not_star_dict(mock_db, monkeypatch):
    tp.TEAM_NAME_TO_ID["liberty"] = 1
    roster_player = MagicMock()
    roster_player.player_id = 99
    roster_player.player_name = "Role Player Not In Star Dict"

    injury = MagicMock()
    injury.status = "out"

    games = [_game(30, 18, 28.0) for _ in range(8)]
    monkeypatch.setattr(tp, "_load_recent_games_for_injury", lambda pid: games)

    def query_side_effect(model):
        chain = MagicMock()
        if model is WNBATeamRoster:
            chain.filter_by.return_value.all.return_value = [roster_player]
        elif model is WNBAPlayerInjuryStatus:
            chain.filter_by.return_value.first.return_value = injury
        else:
            chain.filter_by.return_value.all.return_value = []
            chain.filter_by.return_value.first.return_value = None
        return chain

    mock_db.query.side_effect = query_side_effect
    impact, injured = tp.calculate_injury_impact("Liberty", date(2026, 6, 15))
    assert impact < 0
    assert len(injured) == 1
    assert injured[0]["player"] == "Role Player Not In Star Dict"
    assert injured[0]["method"] == "usage"
