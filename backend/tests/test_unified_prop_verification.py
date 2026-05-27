"""Unified + prop verification fixes for YetAI-placed MLB props."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.simple_unified_bet_model import BetType, SimpleUnifiedBet
from app.services.player_prop_verification_service import PlayerPropVerificationService


def test_determine_sport_from_mlb_column():
    bet = MagicMock()
    bet.league = None
    bet.sport_key = None
    bet.sport = "MLB"
    assert PlayerPropVerificationService()._determine_sport_from_bet(bet) == "mlb"


def test_game_date_uses_commence_time_not_missing_attr():
    bet = MagicMock()
    bet.commence_time = datetime(2026, 5, 24, 18, 0)
    bet.yetai_bet_id = None
    bet.placed_at = datetime(2026, 5, 27, 12, 0)
    svc = PlayerPropVerificationService()
    assert svc._game_date_for_unified_prop(bet).isoformat() == "2026-05-24"
