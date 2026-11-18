"""EV at the real price: price changes the score, negative EV never passes."""

import math

import pytest

from app.services.auto_pick import ev
from app.services.auto_pick.candidate import BetCandidate, MarketType


def _prop(price, fair=0.5, proj=26.5, line=22.5, stat="points", side="over"):
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="NBA",
        event_id="e",
        selection="x",
        market_line=line,
        market_odds=price,
        our_projection=proj,
        projection_metadata={"stat": stat, "side": side, "fair_prob": fair},
    )


def test_price_changes_ev():
    a, _ = ev.candidate_ev(_prop(+105))
    b, _ = ev.candidate_ev(_prop(-115))
    assert a.ev > b.ev
    assert a.fair_prob == b.fair_prob and a.model_part == b.model_part


def test_shrunk_model_part_points():
    # 4 points above the line, k 0.10, sd 6.5: mean +0.4 -> P(over) about 0.5245.
    e = ev.prop_ev("points", "over", 26.5, 22.5, -110, 0.5)
    assert e.model_part == pytest.approx(0.0245, abs=0.0005)


def test_negative_consensus_ev_is_dropped_even_with_big_gap():
    # Fair 50% at -115: paying more than fair, whatever the projection says.
    e, reason = ev.candidate_ev(_prop(-115, proj=60.0))
    assert e.consensus_ev < 0
    assert reason == "negative_consensus_ev"


def test_small_ev_is_dropped():
    # Fair 50% at +100: consensus EV 0, model part tiny -> under MIN_EV.
    _, reason = ev.candidate_ev(_prop(+100, proj=23.0))
    assert reason == "ev_below_threshold"


def test_passes_when_price_beats_fair_and_model_agrees():
    e, reason = ev.candidate_ev(_prop(+110, proj=26.5))
    assert reason is None and e.ev > ev.MIN_EV


def test_under_side_uses_gap_below_line():
    over = ev.prop_ev("rebounds", "over", 8.0, 6.5, -110, 0.5)
    under = ev.prop_ev("rebounds", "under", 5.0, 6.5, -110, 0.5)
    assert over.model_part == pytest.approx(under.model_part)
    assert over.model_part > 0


def test_no_consensus_price_is_dropped():
    c = _prop(+120, fair=None)
    assert ev.candidate_ev(c) == (None, "no_consensus_price")


def test_single_book_two_way_price_never_passes():
    c = BetCandidate(
        market_type=MarketType.MONEYLINE,
        league="NBA",
        event_id="e",
        selection="Team ML",
        market_line=0.0,
        market_odds=-110,
        our_projection=0.80,
        projection_metadata={"side": "home", "opp_odds": -110},
    )
    e, reason = ev.candidate_ev(c)
    assert e.fair_prob == pytest.approx(0.5)
    assert reason == "negative_consensus_ev"


def _game(mt, price, fair, side="home", line=-3.0, proj=-2.0, **md):
    return BetCandidate(
        market_type=mt,
        league="NBA",
        event_id="e",
        selection="x",
        market_line=line,
        market_odds=price,
        our_projection=proj,
        projection_metadata={"side": side, "fair_prob": fair, **md},
    )


def test_spread_without_consensus_is_dropped():
    c = _game(MarketType.SPREAD, +100, None)
    assert ev.candidate_ev(c) == (None, "no_consensus_price")


def test_spread_ev_comes_from_price_vs_consensus_when_k_is_zero():
    anchor = dict(anchor_k=0.0, model_margin=12.0, margin_scale=6.6)
    e, reason = ev.candidate_ev(_game(MarketType.SPREAD, +110, 0.5, **anchor))
    assert e.model_part == 0.0
    assert e.ev == pytest.approx(0.5 * 2.1 - 1) and reason is None


def test_negative_ev_game_line_is_never_picked():
    # Paying -120 on a 50% consensus: a big model gap cannot rescue it.
    anchor = dict(anchor_k=0.2, model_margin=15.0, margin_scale=6.6)
    e, reason = ev.candidate_ev(_game(MarketType.SPREAD, -120, 0.5, **anchor))
    assert e.consensus_ev < 0 and reason == "negative_consensus_ev"
    e, reason = ev.candidate_ev(_game(MarketType.TOTAL, -120, 0.5, side="over"))
    assert reason == "negative_consensus_ev"


def test_spread_model_part_uses_the_anchor_k_on_the_sides_line():
    # Home -3 (the market margin is 3), raw model margin 7, k 0.1: mean 3.4, so
    # P(cover) = logistic(0.4 / 6.6).
    anchor = dict(anchor_k=0.1, model_margin=7.0, margin_scale=6.6)
    home = ev.game_model_part(_game(MarketType.SPREAD, -110, 0.5, **anchor))
    assert home == pytest.approx(1 / (1 + math.exp(-0.4 / 6.6)) - 0.5)
    # The away side at +3 sees the same game from the other end.
    away = ev.game_model_part(
        _game(MarketType.SPREAD, -110, 0.5, side="away", line=3.0, **anchor)
    )
    assert away == pytest.approx(-home)


def test_moneyline_model_part_and_missing_inputs():
    md = dict(anchor_k=0.1, model_margin=7.0, margin_scale=6.6, market_margin=3.0)
    part = ev.game_model_part(_game(MarketType.MONEYLINE, -150, 0.6, line=0.0, **md))
    lg = lambda x: 1 / (1 + math.exp(-x / 6.6))  # noqa: E731
    assert part == pytest.approx(lg(3.4) - lg(3.0))
    assert ev.game_model_part(_game(MarketType.MONEYLINE, -150, 0.6)) == 0.0
    assert ev.game_model_part(_game(MarketType.TOTAL, -110, 0.5, **md)) == 0.0


def test_nfl_nhl_props_have_no_model_part():
    for stat in ("saves", "shots", "passing_yards", "receiving_yards"):
        e = ev.prop_ev(stat, "over", 300.0, 25.5, +110, 0.5)
        assert e.model_part == 0.0 and e.prob == 0.5


def test_nba_prop_ev_is_unchanged_from_ev_v1():
    # Golden values from ev.py as merged in #191 (01e4495f).
    golden = {
        ("points", "o", 25.7, 24.5, -110, 0.48): (
            0.007364669903075938,
            -0.06957653927594598,
        ),
        ("rebounds", "u", 8.1, 9.5, 105, 0.52): (
            0.01861055123287625,
            0.10415163002739636,
        ),
        ("pra", "o", 40.2, 37.5, -120, 0.55): (
            0.006335875729511553,
            0.01994910550410478,
        ),
        ("threes", "u", 1.9, 2.5, -135, 0.6): (
            0.01709229380798294,
            0.07419769662871101,
        ),
    }
    for args, (part, value) in golden.items():
        e = ev.prop_ev(*args)
        assert (e.model_part, e.ev) == (part, value)
    assert ev.SELECTION_VERSION == "ev-v1"
