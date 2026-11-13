import pytest
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.sub_scores import edge_sub_score, raw_edge


def _cand(market_type, line, projection, odds=-110, side=None, **extra):
    meta = dict(extra)
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
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 5.5, side="over"))
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
    s = edge_sub_score(_cand(MarketType.PLAYER_PROP, 1.0, 100.0, side="over"))
    assert s == 100.0


def test_edge_normalized_per_market_type():
    prop = edge_sub_score(_cand(MarketType.PLAYER_PROP, 5.5, 8.5, side="over"))
    spread = edge_sub_score(_cand(MarketType.SPREAD, -3.5, 6.5, side="home"))
    assert prop != spread


def test_edge_mlb_hits_uses_combined_score_board_confidence():
    c = _cand(MarketType.PLAYER_PROP, 0.5, 0.575, side="over")
    c.projection_metadata["stat"] = "hits"
    c.projection_metadata["combined_score"] = 2.5
    # Line-edge alone would be ~37.5; board confidence at 2.5 is 58.75 (+12% boost in scorer).
    assert edge_sub_score(c) == pytest.approx(58.75 * 1.18, abs=0.2)


# --- spread: home-frame margin vs the picked side's spread ------------------


def test_spread_home_favourite_when_model_likes_away_is_non_positive():
    # Home -5, model margin +3 (home by 3): home must win by 5+ to cover.
    assert raw_edge(_cand(MarketType.SPREAD, -5.0, 3.0, side="home")) == -2.0
    assert edge_sub_score(_cand(MarketType.SPREAD, -5.0, 3.0, side="home")) < 0


def test_spread_away_dog_positive_for_same_game():
    assert raw_edge(_cand(MarketType.SPREAD, 5.0, 3.0, side="away")) == 2.0
    assert edge_sub_score(_cand(MarketType.SPREAD, 5.0, 3.0, side="away")) > 0


def test_spread_home_positive_when_margin_beats_line():
    assert raw_edge(_cand(MarketType.SPREAD, -5.0, 8.0, side="home")) == 3.0


# --- totals: signed by side ---------------------------------------------------


def test_total_under_positive_when_projection_below_line():
    assert raw_edge(_cand(MarketType.TOTAL, 220.5, 214.5, side="under")) == 6.0
    assert raw_edge(_cand(MarketType.TOTAL, 220.5, 214.5, side="over")) == -6.0


def test_total_over_positive_when_projection_above_line():
    assert edge_sub_score(_cand(MarketType.TOTAL, 220.5, 225.5, side="over")) > 0


# --- moneyline: model prob minus no-vig implied -----------------------------


def test_moneyline_favourite_below_no_vig_price_has_negative_edge():
    # -200 / +170: no-vig fav = 0.6667/(0.6667+0.3704) = 0.6429; model says 0.60.
    c = _cand(MarketType.MONEYLINE, 0.0, 0.60, odds=-200, side="home", opp_odds=170)
    assert raw_edge(c) < 0
    assert edge_sub_score(c) < 0


def test_moneyline_positive_when_model_beats_no_vig_price():
    c = _cand(MarketType.MONEYLINE, 0.0, 0.70, odds=-200, side="home", opp_odds=170)
    assert abs(raw_edge(c) - (0.70 - 0.6429)) < 1e-3


def test_moneyline_single_side_uses_plain_implied_probability():
    c = _cand(MarketType.MONEYLINE, 0.0, 0.60, odds=100, side="home", opp_odds=None)
    assert abs(raw_edge(c) - 0.10) < 1e-9


def test_moneyline_no_longer_saturates_at_100():
    c = _cand(MarketType.MONEYLINE, 0.0, 0.55, odds=-110, side="home", opp_odds=-110)
    assert edge_sub_score(c) < 50
