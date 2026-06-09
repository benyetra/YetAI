from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.parlay_selector import (
    ParlaySelector,
    filter_parlay_eligible,
)
from app.services.auto_pick.selector import ScoredCandidate, SelectorConfig


def _leg(
    event_id: str,
    score: float,
    *,
    market_type=MarketType.PLAYER_PROP,
    league: str = "MLB",
    selection: str = "Player OVER 0.5 hits",
    odds: int = -110,
):
    c = BetCandidate(
        market_type=market_type,
        league=league,
        event_id=event_id,
        selection=selection,
        market_line=0.5,
        market_odds=odds,
        our_projection=0.8,
        projection_metadata={"side": "over"},
    )
    return ScoredCandidate(
        candidate=c,
        score=ConfidenceScore(total=score, breakdown={}, reasoning=""),
    )


def test_selects_best_two_leg_parlay_above_minus_125_combined():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _leg("g1", 90, selection="Judge OVER 0.5 hits"),
            _leg("g2", 85, selection="Soto OVER 0.5 hits"),
            _leg("g3", 70, selection="Acuna OVER 0.5 hits"),
        ]
    )
    assert pick is not None
    assert pick.combined_odds > -125
    assert pick.tier == SubscriptionTier.PRO
    assert pick.score.total > 0
    event_ids = {leg.candidate.event_id for leg in pick.legs}
    assert event_ids == {"g1", "g2"}


def test_selects_cross_market_parlay():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _leg(
                "mlb-game-1",
                88,
                market_type=MarketType.SPREAD,
                league="MLB",
                selection="Phillies +3.5",
                odds=-110,
            ),
            _leg(
                "mlb-game-2",
                86,
                market_type=MarketType.MONEYLINE,
                league="MLB",
                selection="Rockies ML",
                odds=+145,
            ),
        ]
    )
    assert pick is not None
    assert pick.combined_odds > -125
    types = {leg.candidate.market_type for leg in pick.legs}
    assert MarketType.SPREAD in types
    assert MarketType.MONEYLINE in types


def test_selects_cross_sport_spread_and_prop():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _leg(
                "nhl-game-1",
                90,
                market_type=MarketType.SPREAD,
                league="NHL",
                selection="Bruins +2.5",
                odds=-115,
            ),
            _leg(
                "mlb-prop-ohtani",
                87,
                market_type=MarketType.PLAYER_PROP,
                league="MLB",
                selection="Shohei Ohtani OVER 4.5 strikeouts",
                odds=-110,
            ),
        ]
    )
    assert pick is not None
    leagues = {leg.candidate.league for leg in pick.legs}
    assert leagues == {"NHL", "MLB"}


def test_skips_same_event_legs():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _leg("g1", 90, selection="Judge OVER 0.5 hits"),
            _leg("g1", 88, selection="Soto OVER 0.5 hits"),
        ]
    )
    assert pick is None


def test_skips_when_combined_odds_worse_than_minus_125():
    sel = ParlaySelector(SelectorConfig(threshold=65.0))
    pick = sel.select_parlay(
        [
            _leg("g1", 90, odds=-300),
            _leg("g2", 88, odds=-300),
        ]
    )
    assert pick is None


def test_filter_parlay_eligible_respects_odds_bounds():
    config = SelectorConfig(threshold=65.0, odds_min=-300, odds_max=400)
    low = _leg("g1", 90, odds=-350)
    high = _leg("g2", 88, odds=450)
    ok = _leg("g3", 80, odds=-110)
    eligible = filter_parlay_eligible([low, high, ok], config)
    assert [sc.candidate.event_id for sc in eligible] == ["g3"]


def test_parlay_accepts_legs_below_straight_pick_threshold():
    """Legs scoring 55–64 qualify for parlay pool but not straight picks."""
    config = SelectorConfig(
        threshold=65.0, parlay_leg_threshold=55.0, parlay_score_threshold=55.0
    )
    pick = ParlaySelector(config).select_parlay(
        [
            _leg("g1", 60, selection="Judge OVER 0.5 hits"),
            _leg("g2", 58, selection="Soto OVER 0.5 hits"),
        ]
    )
    assert pick is not None
    assert pick.combined_odds > -125


def test_parlay_rejects_when_combined_confidence_below_floor():
    config = SelectorConfig(
        threshold=65.0, parlay_leg_threshold=55.0, parlay_score_threshold=55.0
    )
    # Parlay confidence = min(56, 56*0.95) = 53.2
    pick = ParlaySelector(config).select_parlay(
        [
            _leg("g1", 56, selection="Leg A"),
            _leg("g2", 56, selection="Leg B"),
        ]
    )
    assert pick is None
