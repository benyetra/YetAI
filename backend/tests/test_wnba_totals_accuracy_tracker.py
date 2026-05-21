from unittest.mock import MagicMock

from app.services.etl.wnba import totals_accuracy_tracker as tat


def _proj(total, market=None):
    p = MagicMock()
    p.projected_total = total
    p.market_total = market
    return p


def _actual(total):
    a = MagicMock()
    a.actual_total = total
    return a


def test_compute_window_returns_mae_and_rmse():
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.filter.return_value.all.return_value = [
        (_proj(160.0, market=158.0), _actual(155)),  # err=5, our pick OVER (160>158), actual UNDER (155<158) → wrong
        (_proj(170.0, market=165.0), _actual(172)),  # err=-2, OVER, actual OVER → right
        (_proj(150.0, market=152.0), _actual(148)),  # err=2, UNDER, UNDER → right
    ]
    stats = tat._compute_window(db, start=None, end=None)
    assert stats["total"] == 3
    assert stats["mae"] == 3.0  # (5+2+2)/3
    # 2/3 directionally correct
    assert stats["directional"] is not None
    assert 0.6 <= stats["directional"] <= 0.7


def test_compute_window_handles_empty():
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.filter.return_value.all.return_value = []
    stats = tat._compute_window(db, start=None, end=None)
    assert stats["total"] == 0
    assert stats["mae"] is None


def test_run_writes_one_row_per_nonempty_window(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("app.services.etl.wnba.totals_accuracy_tracker.SessionLocal", lambda: db)
    monkeypatch.setattr(
        "app.services.etl.wnba.totals_accuracy_tracker._compute_window",
        lambda db_, start, end: {"mae": 4.0, "rmse": 5.0, "directional": 0.6, "total": 10},
    )
    result = tat.run()
    assert result == {"status": "ok", "windows_written": 3}
    assert db.merge.call_count == 3
