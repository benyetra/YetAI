from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.selector import BetSelector, ScoredCandidate, SelectorConfig


def _sc(
    event_id,
    total,
    market_type=MarketType.PLAYER_PROP,
    odds=-110,
    league="MLB",
    selection="s",
):
    c = BetCandidate(
        market_type=market_type,
        league=league,
        event_id=event_id,
        selection=selection,
        market_line=0,
        market_odds=odds,
        our_projection=0,
        projection_metadata={},
    )
    return ScoredCandidate(
        candidate=c, score=ConfidenceScore(total=total, breakdown={}, reasoning="")
    )


def test_drops_below_threshold():
    sel = BetSelector(SelectorConfig(threshold=65.0))
    picks = sel.select([_sc("e1", 50), _sc("e2", 64.9)])
    assert picks == []


def test_picks_top_n_by_score():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select(
        [
            _sc("e1", 70),
            _sc("e2", 90),
            _sc("e3", 80),
            _sc("e4", 66),
            _sc("e5", 95),
        ]
    )
    assert [p.candidate.event_id for p in picks] == ["e5", "e2", "e3", "e1"]


def test_correlation_guard_skips_same_event():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([_sc("e1", 90), _sc("e1", 88), _sc("e2", 70)])
    assert [p.candidate.event_id for p in picks] == ["e1", "e2"]


def test_hard_odds_cutoff_drops_extremes():
    sel = BetSelector(SelectorConfig(threshold=65.0, odds_min=-300, odds_max=400))
    picks = sel.select(
        [_sc("e1", 90, odds=-350), _sc("e2", 85, odds=450), _sc("e3", 80, odds=-150)]
    )
    assert [p.candidate.event_id for p in picks] == ["e3"]


def test_tier_assignment_by_rank():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([_sc("e1", 95), _sc("e2", 90), _sc("e3", 85), _sc("e4", 70)])
    assert picks[0].tier == SubscriptionTier.FREE
    assert picks[1].tier == SubscriptionTier.PRO
    assert picks[2].tier == SubscriptionTier.PRO
    assert picks[3].tier == SubscriptionTier.ELITE


def test_fewer_than_max_when_few_eligible():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=4))
    picks = sel.select([_sc("e1", 80)])
    assert len(picks) == 1
    assert picks[0].tier == SubscriptionTier.FREE
