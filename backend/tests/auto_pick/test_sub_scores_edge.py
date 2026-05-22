import pytest
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.sub_scores import edge_sub_score


def _cand(market_type, line, projection, odds=-110):
    return BetCandidate(
        market_type=market_type, league="MLB", event_id="e",
        selection="s", market_line=line, market_odds=odds,
        our_projection=projection, projection_metadata={},
    )

def test_edge_zero_when_projection_equals_line():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 5.5))
    assert s == 0.0

def test_edge_negative_when_projection_worse_than_line():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 4.0))
    assert s < 0

def test_edge_strider_example_high():
    # 9.0 K projection vs 5.5 line -> strong over
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 9.0))
    assert 70 <= s <= 100

def test_edge_caps_at_100():
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 1.0, 100.0))
    assert s == 100.0

def test_edge_normalized_per_market_type():
    prop = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 8.5))
    spread = edge_sub_score(_cand(MarketType.SPREAD, -3.5, -6.5))
    assert prop != spread
