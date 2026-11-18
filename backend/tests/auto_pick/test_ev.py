"""EV at the real price: price changes the score, negative EV never passes."""

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


def test_spreads_have_no_model_probability():
    c = BetCandidate(
        market_type=MarketType.SPREAD,
        league="NBA",
        event_id="e",
        selection="Team -3",
        market_line=-3.0,
        market_odds=+100,
        our_projection=6.0,
        projection_metadata={"side": "home", "fair_prob": 0.5},
    )
    assert ev.candidate_ev(c) == (None, "no_model_probability")
