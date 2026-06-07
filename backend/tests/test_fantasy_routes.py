"""Tests for fantasy API routes (ojg.2 / ojg.3 / ojg.10)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.main import app
from app.services.fantasy_projections import (
    estimate_ownership_pct,
    generate_deterministic_projections,
)


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "user_id": 1}
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_estimate_ownership_pct_is_deterministic():
    first = estimate_ownership_pct(42, 55.0)
    second = estimate_ownership_pct(42, 55.0)
    assert first == second
    assert 5.0 <= first <= 85.0


def test_generate_deterministic_projections_without_db():
    players = [
        {"id": "1", "name": "Player One", "position": "RB", "team": "KC"},
        {"id": "2", "name": "Player Two", "position": "WR", "team": "BUF"},
    ]
    first = generate_deterministic_projections(None, players, [], season=2024, limit=10)
    second = generate_deterministic_projections(
        None, players, [], season=2024, limit=10
    )
    assert first == second
    assert first[0]["projected_points"] >= first[1]["projected_points"]


@patch("app.api.fantasy.matchups.SleeperFantasyService")
def test_trending_route_returns_players(mock_service_cls, client, auth_headers):
    mock_service = mock_service_cls.return_value
    mock_service.get_trending_players = AsyncMock(
        return_value=[
            {
                "player_id": "123",
                "name": "Test Player",
                "position": "WR",
                "team": "KC",
                "trend_type": "add",
                "trend_count": 500,
            }
        ]
    )

    response = client.get("/api/fantasy/trending", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["trending"]) == 1
    assert body["trending"][0]["trend_count"] == 500


@patch("app.api.fantasy.matchups.SleeperFantasyService")
@patch("app.api.fantasy.matchups._resolve_user_platform_id", new_callable=AsyncMock)
def test_matchups_route_builds_head_to_head(
    mock_platform_user, mock_service_cls, client, auth_headers
):
    mock_platform_user.return_value = "owner-1"
    mock_service = mock_service_cls.return_value
    mock_service.get_league_teams = AsyncMock(
        return_value=[
            {
                "team_id": "1",
                "name": "Team A",
                "owner_name": "Owner A",
                "owner_id": "owner-1",
            },
            {
                "team_id": "2",
                "name": "Team B",
                "owner_name": "Owner B",
                "owner_id": "owner-2",
            },
        ]
    )
    mock_service.get_league_matchups = AsyncMock(
        return_value=[
            {
                "matchup_id": "10",
                "team1_id": "1",
                "team2_id": "2",
                "team1_score": 110.5,
                "team2_score": 98.2,
                "team1_starters": [],
                "team2_starters": [],
            }
        ]
    )

    response = client.get("/api/fantasy/matchups/league-abc/3", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["matchups"]) == 1
    assert body["matchups"][0]["team1"]["score"] == 110.5
    assert body["matchups"][0]["user_involved"] is True


@patch("app.api.fantasy.matchups.SleeperFantasyService")
def test_test_sleeper_username_route(mock_service_cls, client, auth_headers):
    mock_service = mock_service_cls.return_value
    mock_service.authenticate_user = AsyncMock(
        return_value={
            "user_id": "999",
            "display_name": "Test User",
            "username": "testuser",
        }
    )

    response = client.get("/api/fantasy/test/sleeper/testuser", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["sleeper_user_id"] == "999"


@patch("app.api.fantasy.matchups.FantasyAnalyticsService")
def test_breakout_candidates_legacy_shim(mock_service_cls, client, auth_headers):
    mock_service_cls.return_value.get_breakout_candidates.return_value = [
        {
            "player_id": 1,
            "player_name": "Breakout WR",
            "position": "WR",
            "team": "KC",
            "breakout_score": 88.0,
            "snap_increase": 12.0,
            "target_share_increase": 5.0,
            "recent_avg_points": 14.2,
            "reasons": ["Usage up"],
        }
    ]

    response = client.get(
        "/api/fantasy/analytics/breakout-candidates/WR", headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["candidates"][0]["player_name"] == "Breakout WR"


@patch(
    "app.services.fantasy_sleeper_unified.fantasy_sleeper_unified.disconnect_league",
    new_callable=AsyncMock,
)
def test_delete_fantasy_league_route(mock_disconnect, client, auth_headers):
    mock_disconnect.return_value = {
        "status": "success",
        "message": "League league-abc removed from your YetAI account",
    }

    response = client.delete("/api/fantasy/leagues/league-abc", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    mock_disconnect.assert_awaited_once_with(1, "league-abc")


def test_prod_verify_fantasy_beat_schedule_registered():
    from scripts.prod_verify_fantasy import _beat_schedule_ok

    result = _beat_schedule_ok()
    assert result["ok"] is True
