"""YetAI bet verification: status scope, game-date inference, stale detection."""

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.models.database_models import YetAIBet, BetType
from app.services.yetai_bets_service_db import (
    YETAI_UNSETTLED_STATUSES,
    YetAIBetsServiceDB,
    clamp_yetai_result,
    game_date_for_yetai_bet,
    yetai_bet_is_stale,
)


def test_clamp_yetai_result_truncates_long_notes():
    long = "Auto-expired: unsettled >24h without verifiable result"
    assert len(long) > 50
    assert len(clamp_yetai_result(long)) == 50
    assert clamp_yetai_result(long).endswith("...")


def test_unsettled_statuses_include_active():
    assert "active" in YETAI_UNSETTLED_STATUSES
    assert "pending" in YETAI_UNSETTLED_STATUSES


def test_game_date_from_event_id():
    bet = YetAIBet(
        id="x",
        title="A vs B",
        description="d",
        bet_type=BetType.PROP,
        selection="Player UNDER 4.5 strikeouts",
        odds=-110,
        confidence=80,
        prediction_factors={"event_id": "mlb-prop-2026-05-24-12345-strikeouts"},
    )
    assert game_date_for_yetai_bet(bet) == date(2026, 5, 24)


def test_game_date_prefers_commence_time():
    bet = YetAIBet(
        id="x",
        title="A vs B",
        description="d",
        bet_type=BetType.PROP,
        selection="Player UNDER 4.5 strikeouts",
        odds=-110,
        confidence=80,
        commence_time=datetime(2026, 5, 25, 18, 0),
        prediction_factors={"event_id": "mlb-prop-2026-05-24-12345-strikeouts"},
    )
    assert game_date_for_yetai_bet(bet) == date(2026, 5, 25)


def test_stale_uses_created_at_when_no_commence_time():
    old = datetime.utcnow() - timedelta(hours=48)
    bet = YetAIBet(
        id="x",
        title="A vs B",
        description="d",
        bet_type=BetType.PROP,
        selection="Player UNDER 4.5 strikeouts",
        odds=-110,
        confidence=80,
        created_at=old,
    )
    cutoff = datetime.utcnow() - timedelta(hours=24)
    assert yetai_bet_is_stale(bet, cutoff) is True


def test_verify_queries_active_not_only_pending():
    service = YetAIBetsServiceDB()
    mock_db = MagicMock()
    active_bet = MagicMock()
    active_bet.id = "active-1"
    active_bet.status = "active"
    active_bet.bet_type = BetType.PROP
    active_bet.sport = "MLB"
    active_bet.game_id = None
    active_bet.selection = "Christian Scott UNDER 4.5 strikeouts"
    active_bet.title = "Mets @ Marlins"
    active_bet.commence_time = None
    active_bet.created_at = datetime.utcnow() - timedelta(hours=1)
    active_bet.prediction_factors = {}

    chain = mock_db.query.return_value.filter.return_value
    chain.all.return_value = [active_bet]

    with (
        patch(
            "app.services.yetai_bets_service_db.SessionLocal",
            return_value=mock_db,
        ),
        patch(
            "app.services.player_prop_verification_service.PlayerPropVerificationService"
        ) as mock_prop_cls,
    ):
        mock_prop = mock_prop_cls.return_value
        mock_prop.verify_yetai_mlb_prop.return_value = (
            "won",
            "Won: Under 4.5 — actual 2",
        )
        result = asyncio.run(service.verify_pending_yetai_bets())

    assert result["success"] is True
    assert result["settled"] == 1
    assert active_bet.status == "won"
    mock_prop.verify_yetai_mlb_prop.assert_called_once()


def test_lost_evaluation_error_mlb_prop_is_retryable():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="x",
        title="A @ B",
        description="d",
        bet_type=BetType.PROP,
        selection="Connor Prielipp UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="MLB",
        status="lost",
        result="Evaluation error: UnifiedBetVerificationService...",
    )
    assert service._is_retryable_error_loss(bet) is True


def test_lost_evaluation_error_baseball_mlb_is_retryable():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="y",
        title="A @ B",
        description="d",
        bet_type=BetType.PROP,
        selection="Pitcher UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="baseball_mlb",
        status="lost",
        result="Evaluation error: timeout",
    )
    assert service._is_retryable_error_loss(bet) is True


def test_retryable_error_allows_evaluation_prefix_variants():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="z",
        title="A @ B",
        description="d",
        bet_type=BetType.PROP,
        selection="Pitcher UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="MLB",
        status="lost",
        result="Evaluation failed: timeout",
    )
    assert service._is_retryable_error_loss(bet) is True
