"""Tests for persisted trade proposal history (YetAI-nk3)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.fantasy_models import (
    FantasyLeague,
    FantasyPlatform,
    FantasyTeam,
    FantasyUser,
    Trade,
    TradeEvaluation,
    TradeGrade,
    TradeStatus,
)
from app.services.fantasy_trade_history import (
    get_trade_proposal,
    list_trade_proposals,
)


def _sample_trade(*, trade_id: int = 1, league_id: int = 10) -> Trade:
    team1 = FantasyTeam(
        id=101,
        league_id=league_id,
        platform_team_id="1",
        name="Team Alpha",
        owner_name="Alice",
    )
    team2 = FantasyTeam(
        id=102,
        league_id=league_id,
        platform_team_id="2",
        name="Team Beta",
        owner_name="Bob",
    )
    trade = Trade(
        id=trade_id,
        league_id=league_id,
        team1_id=101,
        team2_id=102,
        proposed_by_team_id=101,
        status=TradeStatus.PROPOSED,
        team1_gives={"players": ["p1"], "picks": [], "faab": 0},
        team2_gives={"players": ["p2"], "picks": [2026], "faab": 25},
        trade_reason="Test trade",
        proposed_at=datetime(2025, 9, 1, 12, 0, 0),
    )
    trade.team1 = team1
    trade.team2 = team2
    trade.evaluations = [
        TradeEvaluation(
            id=501,
            trade_id=trade_id,
            team1_grade=TradeGrade.B_PLUS,
            team2_grade=TradeGrade.B,
            team1_value_given=20.0,
            team1_value_received=19.0,
            team2_value_given=19.0,
            team2_value_received=20.0,
            fairness_score=88.5,
            ai_summary="Fair swap",
            confidence=82.0,
            created_at=datetime(2025, 9, 1, 12, 1, 0),
        )
    ]
    return trade


def test_list_trade_proposals_returns_summaries():
    db = MagicMock()
    league = FantasyLeague(id=10, platform_league_id="league-abc")
    trade = _sample_trade()

    league_query = MagicMock()
    league_query.join.return_value = league_query
    league_query.filter.return_value = league_query
    league_query.first.return_value = league

    trade_query = MagicMock()
    trade_query.filter.return_value = trade_query
    trade_query.order_by.return_value = trade_query
    trade_query.limit.return_value = trade_query
    trade_query.all.return_value = [trade]

    db.query.side_effect = [league_query, trade_query]

    result = list_trade_proposals(
        db, user_id=1, platform_league_id="league-abc", limit=10
    )

    assert result["success"] is True
    assert result["total"] == 1
    proposal = result["proposals"][0]
    assert proposal["trade_id"] == 1
    assert proposal["team1"]["roster_id"] == 1
    assert proposal["team2_gives"]["pick_count"] == 1
    assert proposal["evaluation"]["fairness_score"] == 88.5


def test_list_trade_proposals_unknown_league():
    db = MagicMock()
    league_query = MagicMock()
    league_query.join.return_value = league_query
    league_query.filter.return_value = league_query
    league_query.first.return_value = None
    db.query.return_value = league_query

    result = list_trade_proposals(db, user_id=1, platform_league_id="missing")
    assert result["success"] is False
    assert result["proposals"] == []


def test_get_trade_proposal_enforces_user_ownership():
    db = MagicMock()
    trade = _sample_trade()
    league = FantasyLeague(id=10, platform_league_id="league-abc")

    trade_query = MagicMock()
    trade_query.filter.return_value = trade_query
    trade_query.first.return_value = trade

    league_query = MagicMock()
    league_query.join.return_value = league_query
    league_query.filter.return_value = league_query
    league_query.first.return_value = league

    db.query.side_effect = [trade_query, league_query]

    result = get_trade_proposal(db, user_id=1, trade_id=1)
    assert result["success"] is True
    assert result["evaluation_detail"]["fairness_score"] == 88.5


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "user_id": 1}
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


@patch("app.api.fantasy.trade_analyzer.list_trade_proposals")
def test_list_saved_trade_proposals_route(mock_list, client, auth_headers):
    mock_list.return_value = {
        "success": True,
        "league_id": "league-abc",
        "proposals": [{"trade_id": 1}],
        "total": 1,
    }
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(
        "/api/v1/fantasy/trade-analyzer/proposals?league_id=league-abc",
        headers=auth_headers,
    )

    app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    mock_list.assert_called_once()


@patch("app.api.fantasy.trade_analyzer.get_trade_proposal")
def test_get_saved_trade_proposal_route(mock_get, client, auth_headers):
    mock_get.return_value = {
        "success": True,
        "trade_id": 1,
        "league_id": "league-abc",
    }
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(
        "/api/v1/fantasy/trade-analyzer/proposals/1",
        headers=auth_headers,
    )

    app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 200
    assert response.json()["trade_id"] == 1
