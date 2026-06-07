"""Tests for Sleeper-backed trade asset validation."""

from unittest.mock import MagicMock, patch

from app.models.fantasy_models import FantasyLeague, FantasyPlatform, FantasyTeam
from app.services.trade_analyzer_service import TradeAnalyzerService


def _make_service_with_league(platform_league_id: str = "sleeper-league-1"):
    db = MagicMock()
    league = FantasyLeague(
        id=7,
        platform=FantasyPlatform.SLEEPER,
        platform_league_id=platform_league_id,
    )
    team = FantasyTeam(id=10, platform_team_id="3", league_id=7)

    def query_side_effect(model):
        query = MagicMock()
        if model is FantasyLeague:
            query.filter.return_value.first.return_value = league
        elif model is FantasyTeam:
            query.filter.return_value.first.return_value = team
        else:
            query.filter.return_value.first.return_value = None
        return query

    db.query.side_effect = query_side_effect
    return TradeAnalyzerService(db)


@patch("httpx.Client")
def test_validate_team_assets_uses_sleeper_roster_players(mock_client_cls):
    service = _make_service_with_league()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"roster_id": 3, "players": ["player-a", "player-b"]},
        {"roster_id": 4, "players": ["player-c"]},
    ]
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_response

    assert service._validate_team_assets(
        10,
        {"players": ["player-a"]},
        pick_registry={},
        league_id=7,
    )
    assert not service._validate_team_assets(
        10,
        {"players": ["player-z"]},
        pick_registry={},
        league_id=7,
    )
