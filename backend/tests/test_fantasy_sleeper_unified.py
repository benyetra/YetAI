"""Tests for canonical Sleeper integration (YetAI-ojg.1)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.fantasy_models import FantasyPlatform, FantasyUser
from app.services.fantasy_connection_service import fantasy_connection_service
from app.services.fantasy_sleeper_unified import (
    FantasySleeperUnifiedService,
    _safe_int,
)


@pytest.mark.asyncio
async def test_connect_creates_fantasy_user_and_mirrors_sleeper_id():
    service = FantasySleeperUnifiedService()
    db = MagicMock()
    user = MagicMock()
    user.sleeper_user_id = None

    db.query.return_value.filter.return_value.first.side_effect = [
        None,  # no existing FantasyUser
        user,  # User lookup for mirror
    ]

    with patch.object(
        service.sleeper,
        "authenticate_user",
        AsyncMock(
            return_value={
                "user_id": "12345",
                "username": "testuser",
                "display_name": "Test User",
            }
        ),
    ):
        result = await service.connect(1, "testuser", db=db)

    assert result["status"] == "success"
    assert result["connection"]["platform_user_id"] == "12345"
    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert user.sleeper_user_id == "12345"


@pytest.mark.asyncio
async def test_fantasy_connection_service_delegates_to_unified():
    with patch(
        "app.services.fantasy_connection_service.fantasy_sleeper_unified.connect",
        AsyncMock(return_value={"status": "success"}),
    ) as connect_mock:
        result = await fantasy_connection_service.connect_platform(
            1, "sleeper", {"username": "testuser"}
        )

    assert result["status"] == "success"
    connect_mock.assert_awaited_once_with(1, "testuser")


@pytest.mark.asyncio
async def test_sync_league_persists_fantasy_league_metadata():
    service = FantasySleeperUnifiedService()
    db = MagicMock()
    connection = MagicMock()
    connection.id = 99
    connection.platform = FantasyPlatform.SLEEPER

    db.query.return_value.filter.return_value.first.side_effect = [
        connection,  # FantasyUser
        None,  # FantasyLeague
    ]

    with patch.object(
        service.sleeper,
        "get_league_details",
        AsyncMock(
            return_value={
                "name": "Champions League",
                "season": 2025,
                "league_data": {
                    "season": 2025,
                    "name": "Champions League",
                    "total_rosters": 12,
                },
                "scoring_type": "ppr",
                "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "BN"],
            }
        ),
    ):
        result = await service.sync_league(1, "league-abc", db=db)

    assert result["status"] == "success"
    assert result["league_id"] == "league-abc"
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_safe_int_coerces_empty_strings_to_none():
    assert _safe_int("") is None
    assert _safe_int("  ") is None
    assert _safe_int("245") == 245
    assert _safe_int(26) == 26
    assert _safe_int("n/a") is None


@pytest.mark.asyncio
async def test_sync_fantasy_players_sanitizes_empty_numeric_fields():
    service = FantasySleeperUnifiedService()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    with patch.object(
        service.sleeper,
        "_get_all_players",
        AsyncMock(
            return_value={
                "9999": {
                    "first_name": "Test",
                    "last_name": "Player",
                    "position": "WR",
                    "active": True,
                    "team": "",
                    "age": "",
                    "height": "72",
                    "weight": "",
                    "college": "Alabama",
                    "years_exp": "",
                    "injury_status": None,
                    "injury_body_part": "",
                }
            }
        ),
    ):
        result = await service.sync_fantasy_players(db)

    assert result["created"] == 1
    inserted = db.bulk_insert_mappings.call_args[0][1][0]
    assert inserted["age"] is None
    assert inserted["weight"] is None
    assert inserted["experience"] is None
    assert inserted["height"] == "72"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_leagues_includes_prior_season_when_current_is_empty():
    from app.services.sleeper_fantasy_service import SleeperFantasyService

    service = SleeperFantasyService()

    async def fake_get(url: str):
        request = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if url.endswith("/leagues/nfl/2026"):
            response.json.return_value = []
        elif url.endswith("/leagues/nfl/2025"):
            response.json.return_value = [
                {
                    "league_id": "1257417114529054720",
                    "name": "Mike's Hard Fantasy Football",
                    "total_rosters": 12,
                    "scoring_settings": {"rec": 1},
                    "roster_positions": ["QB", "RB"],
                }
            ]
        else:
            response.json.return_value = []
        return response

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(service, "_league_seasons_to_fetch", return_value=[2026, 2025]),
        patch(
            "app.services.sleeper_fantasy_service.httpx.AsyncClient",
            return_value=mock_client,
        ),
        patch.object(
            service,
            "get_league_details",
            AsyncMock(return_value={"teams": [], "league_data": {}}),
        ),
    ):
        leagues = await service.get_user_leagues("644638080736759808")

    assert len(leagues) == 1
    assert leagues[0]["league_id"] == "1257417114529054720"
    assert leagues[0]["season"] == 2025
