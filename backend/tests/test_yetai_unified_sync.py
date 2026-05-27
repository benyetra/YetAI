"""Sync YetAI pick rows from graded placed bets."""

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


def test_sync_yetai_from_unified_bet_updates_expired_yetai_row():
    service = YetAIBetsServiceDB()
    db = MagicMock()
    yetai = SimpleNamespace(
        id="pick-1",
        status="expired",
        settled_at=None,
        result=None,
    )
    unified = SimpleNamespace(
        yetai_bet_id="pick-1",
        status=BetStatus.WON,
        settled_at=None,
        reasoning="Scott Ks over 5.5",
    )
    db.query.return_value.filter.return_value.first.return_value = yetai

    assert service.sync_yetai_from_unified_bet(db, unified) is True
    assert yetai.status == "won"
    assert yetai.settled_at is not None
    assert "Scott" in yetai.result


def test_sync_yetai_from_unified_bet_skips_when_no_link():
    service = YetAIBetsServiceDB()
    unified = SimpleNamespace(
        yetai_bet_id=None,
        status=BetStatus.WON,
        settled_at=None,
        reasoning="",
    )
    assert service.sync_yetai_from_unified_bet(MagicMock(), unified) is False
