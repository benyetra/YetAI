"""Offline tests for WNBA backtest runner window + synthetic scoring path."""

from datetime import date
from unittest.mock import MagicMock

from app.services.etl.wnba.backtest.runner import _window_bounds, run_backtest_replay


def test_window_bounds_quick():
    start, end = _window_bounds(start=None, end=date(2026, 8, 12), quick=True)
    assert end == date(2026, 8, 12)
    assert start == date(2026, 6, 28)


def test_run_backtest_replay_empty_session(monkeypatch):
    session = MagicMock()
    # query().join().filter().filter().all() → []
    chain = MagicMock()
    chain.join.return_value.filter.return_value.filter.return_value.all.return_value = (
        []
    )
    session.query.return_value = chain

    result = run_backtest_replay(
        session, start=date(2026, 5, 1), end=date(2026, 5, 31), quick=False
    )
    assert result["status"] == "ok"
    assert result["spreads"]["n_rows"] == 0
    assert result["totals"]["n_rows"] == 0
    assert result["props"]["points"]["n_rows"] == 0
