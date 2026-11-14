"""L23: NBA totals ML output obeys the version record gate."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.etl.nba import totals_baseline as tb
from app.services.etl.nba import totals_ml as tml

START = date(2026, 11, 1)
HOME, AWAY = "Boston Celtics", "New York Knicks"


def test_recent_bias_of_unbiased_finals_is_near_zero():
    finals = [
        tb.Final(START + timedelta(days=i), HOME, AWAY, 110, 110) for i in range(60)
    ]
    old, _ = tb.recent_bias(finals, START + timedelta(days=60))
    assert abs(old) < 0.5


# ---- L23: ML output goes through recommend() with the projector's record ----


def _ml_proj(edge, record):
    return {
        "projected_total": 200.0 + edge,
        "market_total": 200.0,
        "recommendation": "NO_PLAY",
        "confidence_score": 0.5,
        "factors": {"pick_record": list(record)} if record is not None else {},
    }


def test_ml_losing_record_blocks_big_edge():
    p = _ml_proj(6.0, (10, 40))
    tml._recompute_market_fields(p)
    assert p["recommendation"] == "NO_PLAY"
    assert "below breakeven" in p["factors"]["recommendation_note"]


def test_ml_small_edge_is_no_play():
    p = _ml_proj(3.0, (30, 40))
    tml._recompute_market_fields(p)
    assert p["recommendation"] == "NO_PLAY"


def test_ml_winning_record_big_edge_is_over():
    p = _ml_proj(6.0, (30, 40))
    tml._recompute_market_fields(p)
    assert p["recommendation"] == "OVER"


def test_ml_missing_record_is_unproven():
    p = _ml_proj(-6.0, None)
    tml._recompute_market_fields(p)
    assert p["recommendation"] == "NO_PLAY"
    assert "withheld" in p["factors"]["recommendation_note"]
