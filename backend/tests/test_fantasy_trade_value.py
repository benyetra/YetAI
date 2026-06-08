"""Tests for deterministic fantasy trade values."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.fantasy.trade_value import calculate_realistic_trade_value
from app.core.auth import get_current_user
from app.main import app
from app.services.fantasy_trade_value import (
    calculate_deterministic_trade_value,
    select_trade_partner,
    stable_unit,
)
from app.services.trade_analyzer_service import TradeAnalyzerService


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "user_id": 1}
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_stable_unit_is_deterministic():
    assert stable_unit("player-42") == stable_unit("player-42")
    assert 0.0 <= stable_unit("any-seed") < 1.0


def test_trade_value_is_deterministic_for_same_player():
    player = {"id": "1234", "position": "WR", "age": 26, "team": "KC"}
    first = calculate_deterministic_trade_value(player, scoring_type="ppr")
    second = calculate_deterministic_trade_value(player, scoring_type="ppr")
    assert first == second
    assert 8.0 <= first <= 45.0


def test_trade_value_differs_by_scoring_type():
    player = {"id": "1234", "position": "WR", "age": 26, "team": "KC"}
    ppr = calculate_deterministic_trade_value(player, scoring_type="ppr")
    standard = calculate_deterministic_trade_value(player, scoring_type="standard")
    assert ppr != standard


def test_realistic_trade_value_wr_ppr_gt_standard():
    player = {"id": "wr-42", "position": "WR", "age": 26, "team": "KC"}
    ppr = calculate_realistic_trade_value(player, scoring_type="ppr")
    standard = calculate_realistic_trade_value(player, scoring_type="standard")
    assert ppr > standard


def test_analytics_game_points_respects_scoring_type():
    row = {"ppr_points": 20.0, "half_ppr_points": 17.5, "standard_points": 15.0}
    assert TradeAnalyzerService._analytics_game_points(row, "ppr") == 20.0
    assert TradeAnalyzerService._analytics_game_points(row, "half_ppr") == 17.5
    assert TradeAnalyzerService._analytics_game_points(row, "standard") == 15.0


@patch(
    "app.services.fantasy_sleeper_trade_proposal.load_league_pick_context",
    new_callable=AsyncMock,
)
@patch("app.services.sleeper_fantasy_service.SleeperFantasyService")
def test_quick_analysis_uses_half_ppr_league_scoring(
    mock_service_cls, mock_load_pick_ctx, client, auth_headers
):
    mock_service = mock_service_cls.return_value
    mock_service._get_all_players = AsyncMock(
        return_value={
            "p1": {
                "first_name": "Test",
                "last_name": "Receiver",
                "position": "WR",
                "team": "KC",
                "age": 26,
                "active": True,
            }
        }
    )
    half_ppr_league = {
        "league_id": "lg-half",
        "scoring_settings": {"rec": 0.5},
        "settings": {"type": 0},
        "season": "2025",
        "total_rosters": 12,
    }
    mock_load_pick_ctx.return_value = {
        "league": half_ppr_league,
        "traded_picks": [],
        "pick_registry": {},
        "is_dynasty": False,
    }

    payload = {
        "league_id": "lg-half",
        "team1_id": 1,
        "team2_id": 2,
        "team1_gives": {"players": ["p1"], "picks": [], "faab": 0},
        "team2_gives": {"players": [], "picks": [], "faab": 0},
    }
    response = client.post(
        "/api/v1/fantasy/trade-analyzer/quick-analysis",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 200
    half_ppr_value = response.json()["analysis"]["team1_gives"]["players"][0][
        "trade_value"
    ]

    ppr_value = calculate_realistic_trade_value(
        {
            "first_name": "Test",
            "last_name": "Receiver",
            "position": "WR",
            "team": "KC",
            "age": 26,
        },
        scoring_type="ppr",
    )
    assert half_ppr_value == round(
        calculate_realistic_trade_value(
            {
                "first_name": "Test",
                "last_name": "Receiver",
                "position": "WR",
                "team": "KC",
                "age": 26,
            },
            scoring_type="half_ppr",
        ),
        1,
    )
    assert half_ppr_value != round(ppr_value, 1)


def test_select_trade_partner_is_stable():
    teams = [
        {"team_id": 2, "name": "Beta"},
        {"team_id": 1, "name": "Alpha"},
        {"team_id": 3, "name": "Gamma"},
    ]
    first = select_trade_partner(teams, seed="team-7:QB")
    second = select_trade_partner(teams, seed="team-7:QB")
    assert first == second
    assert first is not None
    assert first["team_id"] in {1, 2, 3}
