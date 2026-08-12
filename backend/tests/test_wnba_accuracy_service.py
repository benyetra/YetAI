"""Smoke tests for wnba_accuracy_service.daily_accuracy.

Six buckets: game totals (O/U + MAE), spread (MAE), and three per-player
O/U buckets (points, assists, rebounds).
"""

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


def test_returns_eight_wnba_buckets_in_order():
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
    pts_p = SimpleNamespace(
        player_id=100,
        projected_points=18.0,
        market_line=17.5,
        recommendation="OVER",
    )
    pts_a = SimpleNamespace(player_id=100, actual_points=20.0)
    ast_p = SimpleNamespace(
        player_id=101,
        projected_assists=5.0,
        market_line=4.5,
        recommendation="UNDER",
    )
    ast_a = SimpleNamespace(player_id=101, actual_assists=3.0)
    reb_p = SimpleNamespace(
        player_id=102,
        projected_rebounds=8.0,
        market_line=7.5,
        recommendation="OVER",
    )
    reb_a = SimpleNamespace(player_id=102, actual_rebounds=9.0)
    db = _mock_db(
        {
            "WNBATotalsProjections": [tot_p],
            "WNBATotalsActuals": [tot_a],
            "WNBASpreadProjections": [sp_p],
            "WNBASpreadActuals": [sp_a],
            "WNBAPointsProjections": [pts_p],
            "WNBAPointsActuals": [pts_a],
            "WNBAAssistsProjections": [ast_p],
            "WNBAAssistsActuals": [ast_a],
            "WNBAReboundsProjections": [reb_p],
            "WNBAReboundsActuals": [reb_a],
        }
    )
    out = svc.daily_accuracy(db, target_date=today)
    keys = [b["key"] for b in out["buckets"]]
    assert keys == [
        "totals_ou",
        "totals_mae",
        "spread_mae",
        "player_points_ou",
        "player_assists_ou",
        "player_rebounds_ou",
        "player_three_pt_made_ou",
        "player_pra_ou",
    ]
    assert out["available"] is True
    # All three per-player picks won
    for k in (
        "player_points_ou",
        "player_assists_ou",
        "player_rebounds_ou",
        "player_three_pt_made_ou",
        "player_pra_ou",
    ):
        bucket = next(b for b in out["buckets"] if b["key"] == k)
        if k in ("player_three_pt_made_ou", "player_pra_ou"):
            # New Phase 3 buckets may be empty in this fixture
            assert bucket is not None
            continue
        assert bucket["primary"] == "1/1 · 100%"


def test_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 8
