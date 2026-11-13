"""Placed bets mirror graded YetAI picks; never the other way round."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.simple_unified_bet_model import BetStatus
from app.services.yetai_bets_service_db import YetAIBetsServiceDB


def test_compute_history_stats_only_counts_graded_picks():
    service = YetAIBetsServiceDB()
    bets = [
        {"status": "won", "odds": "+100"},
        {"status": "lost", "odds": "-110"},
    ]
    stats = service.compute_history_stats(bets, period_days=30)
    assert stats["total"] == 2
    assert stats["win_rate"] == 50.0
    assert stats["units"] == 0.0


def test_sync_unified_from_yetai_when_pick_won_and_placed_bet_lost():
    service = YetAIBetsServiceDB()
    db = MagicMock()
    yetai = SimpleNamespace(
        id="pick-connor",
        status="won",
        settled_at=None,
        result="Won: Under 5.5 — actual 5 (Connor Prielipp)",
    )
    unified = SimpleNamespace(
        id="placed-1",
        yetai_bet_id=None,
        status=BetStatus.LOST,
        amount=250.0,
        potential_win=227.27,
        result_amount=0.0,
        reasoning="Evaluation error: missing db",
        settled_at=None,
    )

    assert service.sync_unified_from_yetai_pick(db, yetai, unified) is True
    assert unified.status == BetStatus.WON
    assert unified.yetai_bet_id == "pick-connor"
    assert unified.result_amount == 250.0 + 227.27


def test_placed_bets_never_write_house_picks():
    assert not hasattr(YetAIBetsServiceDB, "sync_yetai_from_unified_bet")
