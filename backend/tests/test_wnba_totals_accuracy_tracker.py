from datetime import date
from unittest.mock import MagicMock, patch

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


def _make_db(rows):
    """Build a session mock whose entire .query(...).join(...).filter(...).filter(...).all() chain returns `rows`."""
    db = MagicMock(name="Session")
    chain = MagicMock()
    chain.join.return_value.filter.return_value.filter.return_value.all.return_value = (
        rows
    )
    db.query.return_value = chain
    return db


def test_compute_window_returns_mae_and_rmse():
    rows = [
        (
            _proj(160.0, market=158.0),
            _actual(155),
        ),  # err=5; OVER pick, UNDER actual → wrong
        (_proj(170.0, market=165.0), _actual(172)),  # err=-2; OVER, OVER → right
        (_proj(150.0, market=152.0), _actual(148)),  # err=2; UNDER, UNDER → right
    ]
    db = _make_db(rows)
    stats = tat._compute_window(db, start=date(2026, 5, 1), end=date(2026, 5, 21))
    assert stats["total"] == 3
    assert stats["mae"] == 3.0  # (5+2+2)/3
    assert 0.6 <= stats["directional"] <= 0.7  # 2/3 ≈ 0.667


def test_compute_window_handles_empty():
    db = _make_db([])
    stats = tat._compute_window(db, start=date(2026, 5, 1), end=date(2026, 5, 21))
    assert stats == {"mae": None, "rmse": None, "directional": None, "total": 0}


def test_run_writes_one_row_per_nonempty_window(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.etl.wnba.totals_accuracy_tracker.SessionLocal", lambda: db
    )
    monkeypatch.setattr(
        "app.services.etl.wnba.totals_accuracy_tracker._compute_window",
        lambda db_, start, end: {
            "mae": 4.0,
            "rmse": 5.0,
            "directional": 0.6,
            "total": 10,
        },
    )
    with patch("app.services.etl.wnba.totals_accuracy_tracker.replace_matching") as rm:
        result = tat.run()
    assert result == {"status": "ok", "windows_written": 3}
    assert rm.call_count == 1
    assert len(rm.call_args[0][2]) == 3
