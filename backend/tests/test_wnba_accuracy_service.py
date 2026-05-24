"""Smoke tests for wnba_accuracy_service.daily_accuracy."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import wnba_accuracy_service as svc


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


def test_returns_three_wnba_buckets():
    today = date(2026, 5, 23)
    tot_p = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        projected_total=162.0,
        market_total=160.5,
        recommendation="OVER",
    )
    tot_a = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        actual_total=168,
    )
    sp_p = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        projected_margin=4.5,
    )
    sp_a = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        actual_margin=6,
    )
    db = _mock_db(
        {
            "WNBATotalsProjections": [tot_p],
            "WNBATotalsActuals": [tot_a],
            "WNBASpreadProjections": [sp_p],
            "WNBASpreadActuals": [sp_a],
        }
    )
    out = svc.daily_accuracy(db, target_date=today)
    keys = [b["key"] for b in out["buckets"]]
    assert keys == ["totals_ou", "totals_mae", "spread_mae"]
    assert out["available"] is True
    # OVER 160.5, actual 168 → correct
    ou = next(b for b in out["buckets"] if b["key"] == "totals_ou")
    assert ou["primary"] == "1/1 · 100%"


def test_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 3
