"""L4/L23: NBA totals self-correction fits the published error; ML obeys the gate."""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.etl.nba import totals_baseline as tb
from app.services.etl.nba import totals_ml as tml
from app.services.etl.nba import totals_projector as tp

START = date(2026, 11, 1)
HOME, AWAY = "Boston Celtics", "New York Knicks"


def _row(d, actual, published, applied=0.0):
    return SimpleNamespace(
        game_date=d, actual_total=actual, projected_total=published, applied_bias=applied
    )


def _simulate(days, uncorrected=215.0, actual=220.0):
    """Day by day: project with the correction fit on prior published rows."""
    history, errors = [], []
    for i in range(days):
        d = START + timedelta(days=i)
        points, _ = tb.published_bias(history, d)
        published = uncorrected + points
        history.append(_row(d, actual, published, points))
        errors.append(actual - published)
    return errors


def test_persistent_bias_is_driven_to_zero_on_published_error():
    errors = _simulate(tb.BIAS_WINDOW + 40)
    assert abs(sum(errors[-10:]) / 10) < 0.5


def test_old_baseline_bias_cannot_see_published_error():
    # Finals whose plain baseline is unbiased: recent_bias ~0 while the published
    # total (baseline + adjustments) sits 5 points low. This is the L4 defect.
    finals = []
    for i in range(60):
        d = START + timedelta(days=i)
        finals.append(tb.Final(d, HOME, AWAY, 110, 110))  # constant 220 each game
    old, _ = tb.recent_bias(finals, START + timedelta(days=60))
    assert abs(old) < 0.5
    published = [_row(f.game_date, 220, 215.0) for f in finals]
    new, _ = tb.published_bias(published, START + timedelta(days=60))
    assert new > 3.0


def test_unbiased_history_gives_no_correction():
    rng = random.Random(1)
    hist = [
        _row(START + timedelta(days=i), 220, 220 + rng.choice([-6, -3, 3, 6]))
        for i in range(30)
    ]
    points, games = tb.published_bias(hist, START + timedelta(days=30))
    assert abs(points) < 0.5 and games == 30


def test_only_games_before_game_date_count():
    d = START + timedelta(days=5)
    hist = [_row(START + timedelta(days=i), 220, 215.0) for i in range(5)]
    base, _ = tb.published_bias(hist, d)
    hist.append(_row(d, 260, 215.0))  # same-day row must be ignored
    hist.append(_row(d + timedelta(days=1), 260, 215.0))
    assert tb.published_bias(hist, d)[0] == base


def test_calibration_start_and_season_filter():
    old = [_row(date(2026, 10, 1) + timedelta(days=i), 220, 200.0) for i in range(5)]
    assert tb.published_bias(old, START) == (0.0, 0)


def test_clamp_holds():
    hist = [_row(START + timedelta(days=i), 260, 215.0) for i in range(30)]
    points, _ = tb.published_bias(hist, START + timedelta(days=30))
    assert points == tb.BIAS_CLAMP
    hist = [_row(START + timedelta(days=i), 180, 215.0) for i in range(30)]
    assert tb.published_bias(hist, START + timedelta(days=30))[0] == -tb.BIAS_CLAMP


def test_kill_switch_off_uses_baseline_bias(monkeypatch):
    finals = [tb.Final(START + timedelta(days=i), HOME, AWAY, 110, 110) for i in range(3)]
    d = START + timedelta(days=3)
    hist = [_row(START + timedelta(days=i), 220, 210.0) for i in range(3)]
    with patch.object(tp, "published_history_for", return_value=hist), patch.object(
        tp, "recent_bias", return_value=(1.5, 7)
    ):
        monkeypatch.setenv("NBA_TOTALS_PUBLISHED_BIAS_ENABLED", "false")
        assert tp.bias_correction(finals, d) == (1.5, 7, "baseline")
        monkeypatch.delenv("NBA_TOTALS_PUBLISHED_BIAS_ENABLED")
        points, games, source = tp.bias_correction(finals, d)
        assert source == "published" and games == 3 and points > 0


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
    assert p["recommendation"] == "UNDER"
    assert "unproven" in p["factors"]["recommendation_note"]
