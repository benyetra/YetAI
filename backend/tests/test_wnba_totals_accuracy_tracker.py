from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import totals_accuracy_tracker as tat


def _proj(total, market=None, factors=None):
    p = MagicMock()
    p.projected_total = total
    p.market_total = market
    p.factors = factors
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
    assert stats["total"] == 0
    assert stats["mae"] is None
    assert stats["recommend_promote"] is False


def test_compute_window_compares_heuristic_vs_ml_shadow():
    factors = {
        "ml_shadow": {
            "heuristic_total": 160.0,
            "ml_total": 155.0,
        }
    }
    rows = [
        (_proj(160.0, market=158.0, factors=factors), _actual(154)),
        (_proj(170.0, market=165.0, factors=factors), _actual(156)),
    ]
    # Pad to MIN_GAMES_FOR_PROMOTE with same pattern so promote can fire
    while len(rows) < tat.MIN_GAMES_FOR_PROMOTE:
        rows.append((_proj(160.0, market=158.0, factors=factors), _actual(154)))
    db = _make_db(rows)
    stats = tat._compute_window(db, start=date(2026, 5, 1), end=date(2026, 8, 1))
    assert stats["heuristic_mae"] is not None
    assert stats["ml_mae"] is not None
    assert stats["ml_mae"] < stats["heuristic_mae"]
    assert stats["recommend_promote"] is True


def test_should_promote_requires_min_games():
    assert (
        tat.should_promote_totals_ml(
            heuristic_mae=5.0, ml_mae=4.0, ml_games=5, min_games=20
        )
        is False
    )
    assert (
        tat.should_promote_totals_ml(
            heuristic_mae=5.0, ml_mae=4.0, ml_games=20, min_games=20
        )
        is True
    )


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
            "heuristic_mae": 4.2,
            "ml_mae": 3.8,
            "ml_games": 10,
            "recommend_promote": False,
        },
    )
    with patch("app.services.etl.wnba.totals_accuracy_tracker.replace_matching") as rm:
        result = tat.run()
    assert result["status"] == "ok"
    assert result["windows_written"] == 3
    assert rm.call_count == 1
    assert len(rm.call_args[0][2]) == 3
    assert "heuristic_mean_absolute_error" in rm.call_args[0][2][0]
