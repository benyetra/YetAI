"""Yardsticks T2: like-for-like probability CLV, stale closes, short-name join."""

import random
from datetime import date, datetime, timedelta
from itertools import count
from types import SimpleNamespace

from app.services import model_review_service as ms
from app.services.odds_snapshots import short_player_key
from app.services.prop_clv import clv_vs_close, fair_prob_clv

M = "player_points"
_ids = count(1)


def _q(book, line, over, under, seen=None, start=None):
    return SimpleNamespace(
        id=next(_ids),
        book=book,
        line=line,
        over_price=over,
        under_price=under,
        first_seen_at=seen,
        last_seen_at=seen,
        commence_time=start,
    )


def _books(line, shift=0.0):
    prices = [(-110, -110)] * 3 + [(-120, 100), (100, -120)]
    return [_q(f"b{i}", line + shift, o, u) for i, (o, u) in enumerate(prices)]


def test_unchanged_market_is_exactly_zero():
    rows = _books(24.5)
    assert fair_prob_clv("o", 24.5, rows, _books(24.5), M) == 0.0


def test_zero_skill_is_flat_while_the_old_figure_pays_the_vig():
    rng = random.Random(7)
    new, old = [], []
    for _ in range(400):
        side = rng.choice("ou")
        shift = rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0])
        taken, close = _books(24.5), _books(24.5, shift)
        new.append(fair_prob_clv(side, 24.5, taken, close, M))
        old.append(clv_vs_close(side, 24.5, -110, None, close, M)["prob_clv"])
    assert abs(sum(new) / len(new)) < 0.005
    assert -0.035 < sum(old) / len(old) < -0.015


def test_none_without_a_two_way_quote():
    one_sided = [_q("b", 24.5, -110, None)]
    assert fair_prob_clv("o", 24.5, _books(24.5), one_sided, M) is None
    assert fair_prob_clv("o", 24.5, [], _books(24.5), M) is None


DAY = date(2026, 11, 10)
START = datetime(2026, 11, 11, 0, 0)  # naive UTC tip


def _group(name, close_min_before, seen_early=True):
    """Pick-time quote 3 h out, then a close ``close_min_before`` minutes before the start."""
    k = ms.player_key(name)
    early, late = START - timedelta(minutes=180), START - timedelta(
        minutes=close_min_before
    )
    obs = []
    for i, (o, u) in enumerate([(-110, -110)] * 3):
        obs.append(_q(f"b{i}", 24.5, o, u, early, START))
        obs.append(_q(f"b{i}", 25.5, o, u, late, START))
    for q in obs:
        q.last_seen_at = START - timedelta(minutes=close_min_before)
    for q in obs[::2]:
        q.last_seen_at = early
    return {(DAY, M, k, "e1"): obs}


def _row(label, **extra):
    return ms._row(
        25.0,
        24.5,
        30.0,
        "over",
        ("t", DAY.isoformat(), "x"),
        label,
        at=START - timedelta(minutes=170),
        best=("b0", 24.5, -110),
        **extra,
    )


def _key():
    return ("NBA", "player_prop", "points")


def test_close_142_min_out_is_excluded_and_20_min_close_is_used():
    stale = ms._clv_for_key(_key(), [_row("Some Guy")], _group("Some Guy", 142))
    assert (stale["with_close"], stale["stale_close_excluded"]) == (0, 1)
    ok = ms._clv_for_key(_key(), [_row("Some Guy")], _group("Some Guy", 20))
    assert (ok["with_close"], ok["stale_close_excluded"]) == (1, 0)
    assert ok["mean_prob_clv"] is not None and ok["mean_ev_at_taken"] is not None


def test_short_label_joins_full_snapshot_name_but_ambiguous_does_not():
    idx = _group("Connor Hellebuyck", 20)
    key = ("NHL", "player_prop", "saves")
    assert short_player_key("C. Hellebuyck") == short_player_key("Connor Hellebuyck")
    assert short_player_key("c hellebuyck") == "c hellebuyck"
    ms._CLV_MARKETS[key] = M  # reuse the points market in the fake snapshot rows
    try:
        r = ms._clv_for_key(key, [_row("C. Hellebuyck")], idx)
        assert r["with_close"] == 1
        idx.update(_group("Carl Hellebuyck", 20))
        r = ms._clv_for_key(key, [_row("C. Hellebuyck")], idx)
        assert (r["with_close"], r["ambiguous_name"]) == (0, 1)
    finally:
        ms._CLV_MARKETS[key] = "player_total_saves"


def test_clv_units_use_the_called_sides_real_price_and_skip_unpriced_rows():
    key = ("NHL", "player_prop", "saves")

    def row(over, under, actual):
        return ms._row(
            27.0,
            25.5,
            actual,
            "over",
            ("t", DAY.isoformat(), "x"),
            "C. Goalie",
            over_price=over,
            under_price=under,
        )

    rows = [row(-120, 100, 30.0), row(None, None, 30.0)]  # both hit; one has no price
    r = ms._clv_for_key(key, rows, {})
    assert r["priced"] == 1 and r["graded"] == 2
    assert r["units"] == round(100 / 120, 2)  # the -120 hit only; no -110 guess
