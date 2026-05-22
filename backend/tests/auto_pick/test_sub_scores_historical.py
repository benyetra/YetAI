from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import historical_sub_score


def _ctx(rates):
    return ScoringContext(
        weights=ScoringWeights(), score_threshold=65.0, historical_hit_rates=rates
    )


def _cand(mt, league):
    return BetCandidate(
        market_type=mt,
        league=league,
        event_id="e",
        selection="s",
        market_line=0,
        market_odds=-110,
        our_projection=0,
        projection_metadata={},
    )


def test_historical_baseline_when_missing():
    s = historical_sub_score(_cand(MarketType.PLAYER_PROP, "MLB"), _ctx({}))
    assert s == 50.0


def test_historical_breakeven_maps_to_50():
    s = historical_sub_score(
        _cand(MarketType.PLAYER_PROP, "MLB"), _ctx({("player_prop", "MLB"): 0.524})
    )
    assert abs(s - 50.0) < 5.0


def test_historical_strong_hit_rate_high_score():
    s = historical_sub_score(
        _cand(MarketType.PLAYER_PROP, "MLB"), _ctx({("player_prop", "MLB"): 0.65})
    )
    assert s >= 75


def test_historical_poor_hit_rate_low_score():
    s = historical_sub_score(
        _cand(MarketType.PLAYER_PROP, "MLB"), _ctx({("player_prop", "MLB"): 0.40})
    )
    assert s <= 25
