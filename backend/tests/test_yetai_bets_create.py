"""Admin YetAI bet creation (games FK and bet type normalization)."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.bet_models import CreateParlayBetRequest, CreateYetAIBetRequest
from app.models.database_models import BetType
from app.services.yetai_bets_service_db import (
    YetAIBetsServiceDB,
    _ensure_game_row_for_yetai_bet,
)


def test_ensure_game_row_creates_missing_game():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    captured: dict = {}

    def capture_add(obj):
        captured["game"] = obj

    db.add.side_effect = capture_add

    game_id = _ensure_game_row_for_yetai_bet(
        db,
        game_id="evt-wnba-99",
        sport="WNBA",
        home_team="Minnesota Lynx",
        away_team="Golden State Valkyries",
        commence_time=datetime(2026, 6, 4, 23, 0, tzinfo=timezone.utc),
    )

    assert game_id == "evt-wnba-99"
    db.flush.assert_called_once()
    game = captured["game"]
    assert game.id == "evt-wnba-99"
    assert game.sport_key == "basketball_wnba"
    assert game.home_team == "Minnesota Lynx"


def test_ensure_game_row_skips_when_exists():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id="evt-1"
    )

    game_id = _ensure_game_row_for_yetai_bet(
        db,
        game_id="evt-1",
        sport="WNBA",
        home_team="A",
        away_team="B",
        commence_time=None,
    )

    assert game_id == "evt-1"
    db.add.assert_not_called()


def _sample_leg(**overrides):
    base = dict(
        sport="WNBA",
        game="Dallas Wings @ Los Angeles Sparks",
        game_id="evt-wnba-1",
        home_team="Los Angeles Sparks",
        away_team="Dallas Wings",
        bet_type="prop",
        pick="Arike Ogunbowale over 13.5 Points",
        odds="-130",
        confidence=80,
        reasoning="Edge on points",
        game_time="06/05/2026 @07:00 PM EDT",
        commence_time="2026-06-06T02:00:00Z",
    )
    base.update(overrides)
    return CreateYetAIBetRequest(**base)


@patch("app.services.yetai_bets_service_db.SessionLocal")
def test_create_parlay_persists_without_game_time_column(mock_session_local):
    db = MagicMock()
    mock_session_local.return_value = db
    captured: dict = {}

    def capture_add(obj):
        captured["bet"] = obj

    db.add.side_effect = capture_add

    request = CreateParlayBetRequest(
        name="2-Leg WNBA Parlay",
        legs=[
            _sample_leg(),
            _sample_leg(
                sport="WNBA",
                game="Phoenix Mercury @ Portland Fire",
                game_id="evt-wnba-2",
                home_team="Portland Fire",
                away_team="Phoenix Mercury",
                bet_type="spread",
                pick="Spread Portland Fire -2.5",
                odds="-108",
                commence_time="2026-06-06T03:00:00Z",
            ),
        ],
        total_odds="+241",
        confidence=80,
        reasoning="Combined edge on both legs",
    )

    result = asyncio.run(YetAIBetsServiceDB().create_parlay(request, admin_user_id=1))

    assert result["success"] is True
    bet = captured["bet"]
    assert bet.bet_type == BetType.PARLAY
    assert bet.odds == 241.0
    assert len(bet.parlay_legs) == 2
    assert bet.commence_time is not None
    db.commit.assert_called_once()
