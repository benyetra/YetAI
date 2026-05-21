from datetime import date
from unittest.mock import MagicMock

from app.services.etl.wnba import spreads_accuracy_tracker as sat


def _proj(margin, win_prob, rec="HOME", market=-3.0):
    p = MagicMock()
    p.projected_margin = margin
    p.home_win_prob = win_prob
    p.recommendation = rec
    p.market_spread_home = market
    return p


def _actual(margin, home_won):
    a = MagicMock()
    a.actual_margin = margin
    a.home_won = home_won
    return a


def _make_db(rows):
    db = MagicMock(name="Session")
    chain = MagicMock()
    chain.join.return_value.filter.return_value.filter.return_value.all.return_value = rows
    db.query.return_value = chain
    return db


def test_ats_hit_rate_with_home_picks():
    # market spread_home = -3 → home covers if actual_margin > 3
    rows = [
        (_proj(margin=5.0, win_prob=0.7, rec="HOME", market=-3.0), _actual(margin=6, home_won=True)),   # covers
        (_proj(margin=4.0, win_prob=0.65, rec="HOME", market=-3.0), _actual(margin=2, home_won=True)),  # no cover
        (_proj(margin=4.5, win_prob=0.66, rec="HOME", market=-3.0), _actual(margin=8, home_won=True)),  # covers
    ]
    stats = sat._compute_window(_make_db(rows), start=date(2026, 5, 1), end=date(2026, 5, 21))
    assert stats["total"] == 3
    assert stats["ats"] == 2 / 3
    # MAE = avg(|5-6|, |4-2|, |4.5-8|) = avg(1,2,3.5) = 6.5/3
    assert stats["mae"] == 6.5 / 3


def test_brier_score_perfect_predictions_is_zero():
    rows = [
        (_proj(margin=10.0, win_prob=1.0, rec="NO_PLAY"), _actual(margin=15, home_won=True)),
        (_proj(margin=-10.0, win_prob=0.0, rec="NO_PLAY"), _actual(margin=-15, home_won=False)),
    ]
    stats = sat._compute_window(_make_db(rows), start=date(2026, 5, 1), end=date(2026, 5, 21))
    assert stats["brier"] == 0.0
    assert stats["ats"] is None  # all NO_PLAY


def test_no_play_picks_excluded_from_ats():
    rows = [
        (_proj(margin=2.0, win_prob=0.5, rec="NO_PLAY"), _actual(margin=1, home_won=True)),
    ]
    stats = sat._compute_window(_make_db(rows), start=date(2026, 5, 1), end=date(2026, 5, 21))
    assert stats["ats"] is None


def test_run_writes_three_rows(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("app.services.etl.wnba.spreads_accuracy_tracker.SessionLocal", lambda: db)
    monkeypatch.setattr(
        "app.services.etl.wnba.spreads_accuracy_tracker._compute_window",
        lambda db_, start, end: {"mae": 4.5, "ats": 0.55, "brier": 0.22, "buckets": [], "total": 12},
    )
    result = sat.run()
    assert result == {"status": "ok", "windows_written": 3}
    assert db.merge.call_count == 3
