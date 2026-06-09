import pytest
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.sub_scores import edge_sub_score


def _cand(market_type, line, projection, odds=-110, side=None):
    meta = {}
    if side:
        meta["side"] = side
    return BetCandidate(
        market_type=market_type,
        league="MLB",
        event_id="e",
        selection="s",
        market_line=line,
        market_odds=odds,
        our_projection=projection,
        projection_metadata=meta,
    )


def test_edge_zero_when_projection_equals_line():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 5.5))
    assert s == 0.0


def test_edge_negative_when_projection_worse_than_line():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 4.0, side="over"))
    assert s < 0


def test_edge_under_side_positive_when_projection_below_line():
    c = _cand(MarketType.PLAYER_PROP, 5.5, 4.0)
    c.projection_metadata["side"] = "under"
    s = edge_sub_score(c)
    assert s > 0


def test_edge_strider_example_high():
    # 9.0 K projection vs 5.5 line -> strong over
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 9.0, side="over"))
    assert 70 <= s <= 100


def test_edge_caps_at_100():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 1.0, 100.0))
    assert s == 100.0


def test_edge_normalized_per_market_type():
    prop = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 8.5))
    spread = edge_sub_score(_cand(MarketType.SPREAD, -3.5, -6.5))
    assert prop != spread


def test_edge_mlb_hits_uses_combined_score_board_confidence():
    c = _cand(MarketType.PLAYER_PROP, 0.5, 0.575, side="over")
    c.projection_metadata["stat"] = "hits"
    c.projection_metadata["combined_score"] = 2.5
    # Line-edge alone would be ~37.5; board confidence at 2.5 is 58.75 (+12% boost in scorer).
    assert edge_sub_score(c) == pytest.approx(58.75 * 1.18, abs=0.2)
