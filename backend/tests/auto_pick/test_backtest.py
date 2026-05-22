from datetime import date
from unittest.mock import MagicMock

from app.services.auto_pick.backtest import run_backtest


def test_backtest_returns_summary_shape_when_no_history():
    db = MagicMock()
    db.query.return_value.order_by.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = []

    result = run_backtest(date(2026, 2, 1), date(2026, 2, 3), db)

    assert "by_tier" in result
    assert set(result["by_tier"].keys()) == {"free", "pro", "elite"}
    assert "overall_hit_rate" in result
    assert "calibration" in result
    # No history yet -> all zeros, no errors
    assert result["overall_hit_rate"] is None
    for tier in ("free", "pro", "elite"):
        assert result["by_tier"][tier]["total"] == 0


def test_backtest_handles_empty_range():
    db = MagicMock()
    db.query.return_value.order_by.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = []

    # end before start -> zero iterations
    result = run_backtest(date(2026, 2, 5), date(2026, 2, 1), db)
    assert result["overall_hit_rate"] is None
