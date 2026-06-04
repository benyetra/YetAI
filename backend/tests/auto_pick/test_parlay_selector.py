from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.parlay_selector import ParlaySelector
from app.services.auto_pick.selector import ScoredCandidate, SelectorConfig


def _hit_leg(
    event_id: str,
    score: float,
    *,
    player: str = "Player",
    odds: int = -110,
):
    c = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id=event_id,
        selection=f"{player} OVER 0.5 hits",
        market_line=0.5,
        market_odds=odds,
        our_projection=0.8,
        projection_metadata={
            "stat": "hits",
            "side": "over",
            "parlay_eligible": True,
        },
    )
    return ScoredCandidate(
        candidate=c,
        score=ConfidenceScore(total=score, breakdown={}, reasoning=""),
    )


def test_selects_best_two_leg_hit_parlay_above_minus_125_combined():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _hit_leg("g1", 90, player="Judge"),
            _hit_leg("g2", 85, player="Soto"),
            _hit_leg("g3", 70, player="Acuna"),
        ]
    )
    assert pick is not None
    assert pick.combined_odds > -125
    assert pick.tier == SubscriptionTier.PRO
    assert pick.score.total > 0
    event_ids = {leg.candidate.event_id for leg in pick.legs}
    assert event_ids == {"g1", "g2"}


def test_skips_same_game_legs():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _hit_leg("g1", 90, player="Judge"),
            _hit_leg("g1", 88, player="Soto"),
        ]
    )
    assert pick is None


def test_skips_when_combined_odds_worse_than_minus_125():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _hit_leg("g1", 90, odds=-300),
            _hit_leg("g2", 88, odds=-300),
        ]
    )
    assert pick is None


def test_skips_non_hit_props():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    c = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="g1",
        selection="Pitcher OVER 6.5 strikeouts",
        market_line=6.5,
        market_odds=-110,
        our_projection=8.0,
        projection_metadata={"stat": "strikeouts", "side": "over"},
    )
    sc = ScoredCandidate(
        candidate=c,
        score=ConfidenceScore(total=90, breakdown={}, reasoning=""),
    )
    assert sel.select_parlay([sc, _hit_leg("g2", 90)]) is None
