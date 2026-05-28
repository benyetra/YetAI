"""Unified + prop verification fixes for YetAI-placed MLB props."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.simple_unified_bet_model import BetStatus, BetType, SimpleUnifiedBet
from app.services.unified_bet_verification_service import UnifiedBetVerificationService
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


def test_unified_prop_evaluation_does_not_require_missing_self_db():
    service = UnifiedBetVerificationService()
    bet = MagicMock()
    bet.id = "bet-1234"
    bet.bet_type = BetType.PROP
    bet.amount = 100.0
    bet.potential_win = 90.0

    with patch(
        "app.services.player_prop_verification_service.PlayerPropVerificationService.verify_single_prop",
        new=AsyncMock(
            return_value={
                "status": BetStatus.LOST,
                "result_amount": 0.0,
                "reasoning": "MLB prop graded",
            }
        ),
    ):
        result = AsyncMock()
        import asyncio

        result = asyncio.run(service._evaluate_bet_outcome(bet, 0, 0))

    assert result.status == BetStatus.LOST
    assert result.reasoning == "MLB prop graded"


def test_fetch_mlb_player_stats_uses_game_date_season():
    service = PlayerPropVerificationService()
    game_date = datetime(2026, 5, 27).date()

    search_response = MagicMock()
    search_response.raise_for_status.return_value = None
    search_response.json.return_value = {"people": [{"id": 123}]}

    stats_response = MagicMock()
    stats_response.raise_for_status.return_value = None
    stats_response.json.return_value = {
        "people": [
            {
                "stats": [
                    {
                        "type": {"displayName": "gameLog"},
                        "splits": [{"date": "2026-05-27", "stat": {"strikeouts": 10}}],
                    }
                ]
            }
        ]
    }

    with patch(
        "app.services.player_prop_verification_service.requests.get",
        side_effect=[search_response, stats_response],
    ) as mock_get:
        stats = service._fetch_mlb_player_stats("Gerrit Cole", "strikeouts", game_date)

    assert stats == {"strikeouts": 10}
    assert "season=2026" in mock_get.call_args_list[1].args[0]


def test_retryable_evaluation_error_prop_is_detected():
    service = UnifiedBetVerificationService()
    bet = MagicMock()
    bet.status = BetStatus.LOST
    bet.bet_type = BetType.PROP
    bet.reasoning = "Evaluation error: missing session"
    assert service._is_retryable_evaluation_error(bet) is True


def test_non_prop_loss_is_not_retryable():
    service = UnifiedBetVerificationService()
    bet = MagicMock()
    bet.status = BetStatus.LOST
    bet.bet_type = BetType.SPREAD
    bet.reasoning = "Evaluation error: parse issue"
    assert service._is_retryable_evaluation_error(bet) is False
