"""Tests for trade analyzer league teams route."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.fantasy.trade_analyzer import _map_league_teams_for_frontend
from app.core.auth import get_current_user
from app.main import app


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "user_id": 1}
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_map_league_teams_for_frontend_uses_roster_id_as_id():
    teams = _map_league_teams_for_frontend(
        [
            {
                "team_id": "3",
                "name": "Champions",
                "owner_name": "Alice",
                "owner_id": "owner-1",
            },
            {
                "team_id": "invalid",
                "name": "Skip Me",
                "owner_name": "Bob",
            },
        ]
    )

    assert teams == [
        {
            "id": 3,
            "team_id": 3,
            "name": "Champions",
            "owner_name": "Alice",
        }
    ]


@patch("app.services.sleeper_fantasy_service.SleeperFantasyService")
def test_trade_analyzer_league_teams_route(mock_service_cls, client, auth_headers):
    mock_service = mock_service_cls.return_value
    mock_service.get_league_teams = AsyncMock(
        return_value=[
            {
                "team_id": "1",
                "name": "Team Alpha",
                "owner_name": "Owner A",
                "owner_id": "owner-a",
            },
            {
                "team_id": "2",
                "name": "Team Beta",
                "owner_name": "Owner B",
                "owner_id": "owner-b",
            },
        ]
    )

    response = client.get(
        "/api/v1/fantasy/trade-analyzer/leagues/league-abc/teams",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["league_id"] == "league-abc"
    assert body["total"] == 2
    assert body["teams"] == [
        {
            "id": 1,
            "team_id": 1,
            "name": "Team Alpha",
            "owner_name": "Owner A",
        },
        {
            "id": 2,
            "team_id": 2,
            "name": "Team Beta",
            "owner_name": "Owner B",
        },
    ]
    mock_service.get_league_teams.assert_awaited_once_with("league-abc")
