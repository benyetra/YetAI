"""Spread ATS + totals O/U buckets in nfl_accuracy_service."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import nfl_accuracy_service as svc


def _mock_db(rows_by_model):
    db = MagicMock()

    def side_effect(model):
        result = MagicMock()
        result.filter.return_value.all.return_value = rows_by_model.get(
            model.__name__, []
        )
        return result

    db.query.side_effect = side_effect
    return db


def test_spread_ats_and_totals_ou_buckets_when_actuals_exist():
    spread_p = SimpleNamespace(
        game_date=date(2026, 9, 7),
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        projected_margin=4.0,
        market_spread_home=-3.0,
        recommendation="HOME",
    )
    spread_a = SimpleNamespace(
        game_date=date(2026, 9, 7),
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        actual_margin=7,
        home_won=True,
    )
    totals_p = SimpleNamespace(
        game_date=date(2026, 9, 7),
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        projected_total=48.0,
        market_total=45.5,
        recommendation="OVER",
    )
    totals_a = SimpleNamespace(
        game_date=date(2026, 9, 7),
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        actual_total=52,
    )

    db = _mock_db(
        {
            "NFLSpreadProjections": [spread_p],
            "NFLSpreadActuals": [spread_a],
            "NFLTotalsProjections": [totals_p],
            "NFLTotalsActuals": [totals_a],
            "QBPredictions": [],
            "QBActuals": [],
            "KickerPredictions": [],
            "KickerActuals": [],
        }
    )

    out = svc.daily_accuracy(db, target_date=date(2026, 9, 7))
    keys = [b["key"] for b in out["buckets"]]
    assert "spread_ats" in keys
    assert "totals_ou" in keys

    spread = next(b for b in out["buckets"] if b["key"] == "spread_ats")
    totals = next(b for b in out["buckets"] if b["key"] == "totals_ou")
    assert spread["primary"] == "1/1 · 100%"
    assert totals["primary"] == "1/1 · 100%"
