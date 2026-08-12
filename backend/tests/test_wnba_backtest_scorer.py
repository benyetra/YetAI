"""Tests for WNBA walk-forward / stored-projection backtest scorer."""

from app.services.etl.wnba.backtest.scorer import (
    american_to_profit,
    score_ats,
    score_totals,
    score_props,
)


def test_american_to_profit_minus_110():
    assert american_to_profit(-110, won=True) == round(100 / 110, 6)
    assert american_to_profit(-110, won=False) == -1.0


def test_score_ats_roi():
    rows = [
        {"recommendation": "HOME", "actual_margin": 10, "market_spread_home": -3.5},
        {"recommendation": "AWAY", "actual_margin": 5, "market_spread_home": -3.5},
        {"recommendation": "NO_PLAY", "actual_margin": 2, "market_spread_home": -3.5},
    ]
    # HOME covers (10 > 3.5), AWAY fails (5 is not < 3.5)
    out = score_ats(rows, odds=-110)
    assert out["n_bets"] == 2
    assert out["hit_rate"] == 0.5
    assert out["roi"] == round((100 / 110 - 1.0) / 2, 6)


def test_score_totals_ou():
    rows = [
        {
            "projected_total": 170,
            "market_total": 165,
            "actual_total": 172,
            "recommendation": "OVER",
        },
        {
            "projected_total": 150,
            "market_total": 160,
            "actual_total": 155,
            "recommendation": "UNDER",
        },
    ]
    out = score_totals(rows, odds=-110)
    assert out["n_bets"] == 2
    assert out["hit_rate"] == 1.0


def test_score_props_roi():
    rows = [
        {
            "projected": 22.0,
            "market_line": 20.5,
            "actual": 25.0,
            "recommendation": "OVER",
        },
        {
            "projected": 18.0,
            "market_line": 20.5,
            "actual": 15.0,
            "recommendation": "UNDER",
        },
        {
            "projected": 20.0,
            "market_line": 20.5,
            "actual": 21.0,
            "recommendation": "NO_PLAY",
        },
    ]
    out = score_props(rows, odds=-110)
    assert out["n_bets"] == 2
    assert out["hit_rate"] == 1.0
    assert out["mae"] == round((3.0 + 3.0 + 1.0) / 3, 6)
