from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.nba import _spread_ml_predict as smp
from app.services.etl.nba import spreads_accuracy_tracker as sat


def test_predict_margin_when_model_loaded(monkeypatch):
    monkeypatch.setattr(smp, "_LOAD_FAILED", False)

    class FakeModel:
        def predict(self, vec):
            return [4.2]

    monkeypatch.setattr(smp, "_MODEL", FakeModel())
    monkeypatch.setattr(
        smp,
        "_METADATA",
        {"features": ["elo_diff", "pace_adj"]},
    )

    margin = smp.predict_margin({"elo_diff": 12.0, "pace_adj": 0.3})
    assert margin == 4.2


def test_predict_margin_none_when_not_loaded(monkeypatch):
    monkeypatch.setattr(smp, "_MODEL", None)
    monkeypatch.setattr(smp, "_METADATA", None)
    monkeypatch.setattr(smp, "_LOAD_FAILED", True)
    assert smp.predict_margin({"elo_diff": 1.0}) is None


def _proj(margin, win_prob, rec="HOME", market=-3.0, method="elo_pace"):
    p = MagicMock()
    p.projected_margin = margin
    p.home_win_prob = win_prob
    p.recommendation = rec
    p.market_spread_home = market
    p.factors = {"method": method, "elo_pace_margin": margin}
    return p


def _actual(margin, home_won):
    a = MagicMock()
    a.actual_margin = margin
    a.home_won = home_won
    return a


def _make_db(rows):
    db = MagicMock(name="Session")
    chain = MagicMock()
    chain.join.return_value.filter.return_value.filter.return_value.all.return_value = (
        rows
    )
    db.query.return_value = chain
    return db


def test_brier_split_by_model_type():
    rows = [
        (
            _proj(margin=5.0, win_prob=1.0, method="elo_pace"),
            _actual(margin=6, home_won=True),
        ),
        (
            _proj(margin=5.0, win_prob=0.0, method="ml"),
            _actual(margin=6, home_won=True),
        ),
    ]
    stats = sat._compute_nba_window(
        _make_db(rows), start=date(2025, 11, 1), end=date(2025, 11, 30)
    )
    assert stats["total"] == 2
    assert stats["brier"] == 0.5
    assert stats["by_method"]["elo_pace"]["brier"] == 0.0
    assert stats["by_method"]["elo_pace"]["count"] == 1
    assert stats["by_method"]["ml"]["brier"] == 1.0
    assert stats["by_method"]["ml"]["count"] == 1


def test_run_persists_by_method_brier(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(
        "app.services.etl.nba.spreads_accuracy_tracker.SessionLocal", lambda: db
    )
    monkeypatch.setattr(
        "app.services.etl.nba.spreads_accuracy_tracker._compute_nba_window",
        lambda db_, start, end: {
            "mae": 4.0,
            "ats": 0.5,
            "brier": 0.22,
            "buckets": [{"bucket": "0.5-0.6", "count": 2, "actual_win_rate": 0.5}],
            "by_method": {
                "elo_pace": {"brier": 0.24, "count": 8},
                "ml": {"brier": 0.18, "count": 4},
            },
            "total": 12,
        },
    )
    with patch("app.services.etl.nba.spreads_accuracy_tracker.replace_matching") as rm:
        result = sat.run()
    assert result == {"status": "ok", "windows_written": 3}
    row = rm.call_args[0][2][0]
    assert row["calibration_buckets"]["by_method"]["ml"]["brier"] == 0.18
    assert row["calibration_buckets"]["by_method"]["elo_pace"]["count"] == 8
