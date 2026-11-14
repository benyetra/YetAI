from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.services import platform_stats as ps


def test_profit_dollars_won_minus_odds():
    bet = MagicMock(status="won", odds=-110.0)
    assert ps._profit_dollars(bet) == pytest.approx(90.91, rel=0.01)


def test_profit_dollars_lost():
    bet = MagicMock(status="lost", odds=-110.0)
    assert ps._profit_dollars(bet) == -100.0


def test_compute_platform_stats_uses_status_not_result(monkeypatch):
    now = datetime.utcnow()
    graded = [
        MagicMock(
            status="won",
            odds=-110.0,
            result="Hit: Scott 3 Ks (under 4.5)",
            settled_at=now - timedelta(days=2),
            created_at=now - timedelta(days=3),
            title="Mets vs Phillies",
            description="edge",
            reasoning=None,
            selection="UNDER 4.5 Ks",
        ),
        MagicMock(
            status="lost",
            odds=150.0,
            result="Miss: line not covered",
            settled_at=now - timedelta(days=1),
            created_at=now - timedelta(days=2),
            title="Cubs vs Reds",
            description="fade",
            reasoning=None,
            selection="Cubs ML",
        ),
    ]

    monkeypatch.setattr(ps, "_graded_bets", lambda _db: graded)

    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 2
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
        []
    )

    monkeypatch.setattr(ps, "public_record", lambda _db: {"label": "L", "stats": {}})
    monkeypatch.setattr(
        ps, "legacy_performance", lambda _db: {"performance_30d": {"win_rate": 0.0}}
    )
    data = ps.compute_platform_stats(db)

    assert data["total_winnings"] == pytest.approx(90.91, rel=0.01)
    assert data["record"]["label"] == "L"
    assert data["performance_30d"] == {"win_rate": 0.0}  # old keys ride along


def _row(status, created, odds=100):
    return {
        "status": status,
        "odds": odds,
        "effective_odds": None,
        "created_at": created,
        "settled_at": created,
    }


def test_legacy_performance_keeps_old_keys_for_real_windows():
    from app.services.yetai_bets_service_db import YetAIBetsServiceDB

    now = datetime(2026, 11, 13, 12)
    d = lambda n: now - timedelta(days=n)  # noqa: E731
    rows = [
        _row("won", d(1)),  # +100 (even odds, $100)
        _row("lost", d(2)),  # -100
        _row("won", d(3)),  # +100
        _row("lost", d(10)),  # prior week: -100
        _row("lost", d(20)),  # 30d only: -100
        _row("void", d(1)),  # not graded
    ]
    svc = YetAIBetsServiceDB()
    svc._history_stat_rows = lambda tier, db, since: rows
    out = ps.legacy_performance(None, svc, now=now)
    p30, p7 = out["performance_30d"], out["performance_7d"]
    assert p30 == {
        "win_rate": 40.0,
        "profit": -100.0,
        "total_bets": 5,
        "wins": 2,
        "losses": 3,
    }
    assert p7["win_rate"] == pytest.approx(66.7) and p7["profit"] == 100.0
    # prior 7d profit was -100, this week +100: (100 - -100) / 100 = +200%
    assert p7["wow_change"] == 200.0


def test_legacy_performance_is_numeric_with_no_graded_bets():
    from app.services.yetai_bets_service_db import YetAIBetsServiceDB

    svc = YetAIBetsServiceDB()
    svc._history_stat_rows = lambda tier, db, since: []
    out = ps.legacy_performance(None, svc, now=datetime(2026, 11, 13))
    assert out["performance_30d"]["win_rate"] == 0.0  # old panel calls .toFixed on it
    assert out["performance_7d"]["wow_change"] == 0.0
