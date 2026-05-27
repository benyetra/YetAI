"""YetAI bets history API helpers."""

from app.services.yetai_bets_service_db import YetAIBetsServiceDB


def test_compute_history_stats_win_rate_and_units():
    service = YetAIBetsServiceDB()
    bets = [
        {"status": "won", "odds": "+100"},
        {"status": "won", "odds": "-110"},
        {"status": "lost", "odds": "-110"},
        {"status": "pushed", "odds": "-110"},
    ]
    stats = service.compute_history_stats(bets, period_days=30)
    assert stats["total"] == 4
    assert stats["won"] == 2
    assert stats["lost"] == 1
    assert stats["pushed"] == 1
    assert stats["win_rate"] == 66.7
    assert stats["units"] == 0.91
