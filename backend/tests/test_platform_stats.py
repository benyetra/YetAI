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

    data = ps.compute_platform_stats(db)

    assert data["total_winnings"] == pytest.approx(90.91, rel=0.01)
    assert data["performance_30d"]["total_bets"] == 2
    assert data["performance_30d"]["wins"] == 1
    assert data["performance_30d"]["losses"] == 1
    assert data["performance_30d"]["profit"] == pytest.approx(-9.09, rel=0.05)
