"""YetAI bets history API helpers."""

from datetime import datetime

from app.services.yetai_bets_service_db import YetAIBetsServiceDB, _utc_iso


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


def test_utc_iso_appends_z_for_naive_datetime():
    dt = datetime(2026, 6, 5, 21, 49, 28)
    assert _utc_iso(dt) == "2026-06-05T21:49:28Z"


def test_history_stats_use_settled_subset_only():
    service = YetAIBetsServiceDB()
    bets = [
        {"status": "won", "odds": "+100"},
        {"status": "pending", "odds": "-110"},
    ]
    stats = service.compute_history_stats(
        [b for b in bets if b["status"] in service.YETAI_HISTORY_STATUSES],
        period_days=90,
    )
    assert stats["total"] == 1
    assert stats["won"] == 1
