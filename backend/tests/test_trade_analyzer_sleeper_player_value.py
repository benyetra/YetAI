"""Trade analyzer value/impact paths with Sleeper player ids (no league sync)."""

from unittest.mock import MagicMock, patch

from app.models.database_models import SleeperPlayer
from app.models.fantasy_models import FantasyLeague, FantasyPlatform, FantasyTeam
from app.services.trade_analyzer_service import TradeAnalyzerService


def _service_with_sleeper_player(
    sleeper_id: str = "player-x",
    position: str = "WR",
    age: int = 27,
):
    db = MagicMock()
    league = FantasyLeague(
        id=7,
        platform=FantasyPlatform.SLEEPER,
        platform_league_id="sleeper-league-1",
    )
    team = FantasyTeam(id=10, platform_team_id="3", league_id=7)
    sleeper_row = SleeperPlayer(
        sleeper_player_id=sleeper_id,
        full_name="Sleeper Only WR",
        position=position,
        team="NYG",
        age=age,
    )

    def query_side_effect(model):
        query = MagicMock()
        if model is FantasyLeague:
            query.filter.return_value.first.return_value = league
        elif model is FantasyTeam:
            query.filter.return_value.first.return_value = team
        elif model is SleeperPlayer:
            query.filter.return_value.first.return_value = sleeper_row
        else:
            chain = query.filter.return_value
            chain.first.return_value = None
            chain.order_by.return_value.first.return_value = None
        return query

    db.query.side_effect = query_side_effect
    return TradeAnalyzerService(db)


@patch(
    "app.services.fantasy_trade_value.calculate_deterministic_trade_value",
    return_value=18.5,
)
def test_get_simple_player_value_sleeper_id(mock_calc):
    service = _service_with_sleeper_player()
    value = service._get_simple_player_value("player-x", scoring_type="half_ppr")
    assert value == 18.5
    mock_calc.assert_called_once()
    assert mock_calc.call_args.kwargs.get("scoring_type") == "half_ppr"


@patch(
    "app.services.fantasy_trade_value.calculate_deterministic_trade_value",
    return_value=22.0,
)
def test_get_player_trade_value_sleeper_id(mock_calc):
    service = _service_with_sleeper_player()
    league_context = {
        "league_id": 7,
        "current_week": 8,
        "is_dynasty": False,
        "scoring_type": "standard",
    }
    result = service._get_player_trade_value("player-x", league_context, {})
    assert result["total_value"] > 0
    assert result["player_name"] == "Sleeper Only WR"
    assert "error" not in result
    mock_calc.assert_called_once()


def test_calculate_age_impact_with_sleeper_ids():
    service = _service_with_sleeper_player(age=32)
    gives = {"players": ["player-x"]}
    receives = {"players": []}
    impact = service._calculate_age_impact(gives, receives)
    assert impact["getting_younger"] is True
    assert impact["average_age_change"] == -32.0
