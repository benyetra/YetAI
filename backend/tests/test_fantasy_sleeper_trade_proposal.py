"""Tests for Sleeper-only trade proposal validation and evaluation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.fantasy_draft_picks import build_league_pick_registry
from app.services.fantasy_sleeper_trade_proposal import (
    propose_sleeper_trade,
    validate_sleeper_trade_assets,
)


def _sample_league() -> dict:
    return {
        "season": "2025",
        "total_rosters": 12,
        "settings": {"type": 0, "draft_rounds": 3},
    }


def _sample_pick_registry(league: dict) -> dict:
    return build_league_pick_registry(league, [])


@pytest.fixture
def mock_rosters():
    return [
        {"roster_id": 1, "players": ["p1", "p2"]},
        {"roster_id": 2, "players": ["p3", "p4"]},
    ]


@pytest.fixture
def sleeper_service():
    service = MagicMock()
    service.get_league = AsyncMock(return_value=_sample_league())
    service.get_league_traded_picks = AsyncMock(return_value=[])
    service._get_all_players = AsyncMock(
        return_value={
            "p1": {
                "first_name": "Alpha",
                "last_name": "One",
                "position": "WR",
                "team": "KC",
                "age": 26,
            },
            "p2": {
                "first_name": "Beta",
                "last_name": "Two",
                "position": "RB",
                "team": "SF",
                "age": 24,
            },
            "p3": {
                "first_name": "Gamma",
                "last_name": "Three",
                "position": "WR",
                "team": "DAL",
                "age": 27,
            },
            "p4": {
                "first_name": "Delta",
                "last_name": "Four",
                "position": "TE",
                "team": "PHI",
                "age": 28,
            },
        }
    )
    return service


@pytest.mark.asyncio
async def test_validate_rejects_player_not_on_roster(sleeper_service, mock_rosters):
    league = _sample_league()
    pick_registry = _sample_pick_registry(league)

    with patch(
        "app.services.fantasy_sleeper_trade_proposal.fetch_league_rosters",
        new=AsyncMock(return_value=mock_rosters),
    ):
        result = await validate_sleeper_trade_assets(
            sleeper_service=sleeper_service,
            platform_league_id="league-123",
            team1_roster_id=1,
            team2_roster_id=2,
            team1_gives={"players": ["p99"], "picks": [], "faab": 0},
            team2_gives={"players": ["p3"], "picks": [], "faab": 0},
            pick_registry=pick_registry,
        )

    assert result["valid"] is False
    assert "doesn't own player" in result["error"]


@pytest.mark.asyncio
async def test_validate_accepts_valid_mock_rosters(sleeper_service, mock_rosters):
    league = _sample_league()
    pick_registry = _sample_pick_registry(league)

    with patch(
        "app.services.fantasy_sleeper_trade_proposal.fetch_league_rosters",
        new=AsyncMock(return_value=mock_rosters),
    ):
        result = await validate_sleeper_trade_assets(
            sleeper_service=sleeper_service,
            platform_league_id="league-123",
            team1_roster_id=1,
            team2_roster_id=2,
            team1_gives={"players": ["p1"], "picks": [], "faab": 0},
            team2_gives={"players": ["p3"], "picks": [], "faab": 0},
            pick_registry=pick_registry,
        )

    assert result == {"valid": True}


@pytest.mark.asyncio
async def test_propose_returns_evaluation_without_db(sleeper_service, mock_rosters):
    with patch(
        "app.services.fantasy_sleeper_trade_proposal.fetch_league_rosters",
        new=AsyncMock(return_value=mock_rosters),
    ):
        result = await propose_sleeper_trade(
            sleeper_service=sleeper_service,
            platform_league_id="league-123",
            team1_roster_id=1,
            team2_roster_id=2,
            team1_gives={"players": ["p1"], "picks": [], "faab": 0},
            team2_gives={"players": ["p3"], "picks": [], "faab": 0},
            persist=False,
            db=None,
        )

    assert result["success"] is True
    assert result["validated"] is True
    assert result["persisted"] is False
    evaluation = result["evaluation"]
    assert evaluation["team1_gives"]["players"][0]["player_id"] == "p1"
    assert evaluation["team2_gives"]["players"][0]["player_id"] == "p3"
    assert "fairness" in evaluation
    assert "insights" in evaluation
    assert "recommendation" in evaluation


@pytest.mark.asyncio
async def test_propose_persist_false_never_touches_trade_table(
    sleeper_service, mock_rosters
):
    db = MagicMock()

    with patch(
        "app.services.fantasy_sleeper_trade_proposal.fetch_league_rosters",
        new=AsyncMock(return_value=mock_rosters),
    ):
        with patch(
            "app.services.fantasy_sleeper_trade_proposal._try_persist_trade",
            new=AsyncMock(),
        ) as persist_mock:
            result = await propose_sleeper_trade(
                sleeper_service=sleeper_service,
                platform_league_id="league-123",
                team1_roster_id=1,
                team2_roster_id=2,
                team1_gives={"players": ["p1"], "picks": [], "faab": 0},
                team2_gives={"players": ["p3"], "picks": [], "faab": 0},
                persist=False,
                db=db,
            )

    persist_mock.assert_not_called()
    assert result["persisted"] is False
