from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import (
    line_movement_sub_score,
    odds_sanity_sub_score,
    model_confidence_sub_score,
)


def _cand(odds=-110, event_id="e", md=None):
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id=event_id,
        selection="OVER",
        market_line=5.5,
        market_odds=odds,
        our_projection=9.0,
        projection_metadata=md or {},
    )


def test_line_movement_neutral_when_no_data():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert line_movement_sub_score(_cand(), ctx) == 50.0


def test_line_movement_bonus_when_market_moves_toward_us():
    ctx = ScoringContext(
        weights=ScoringWeights(),
        score_threshold=65.0,
        line_movement={"e": {"opened_line": 5.5, "current_line": 6.0, "side": "over"}},
    )
    assert line_movement_sub_score(_cand(event_id="e"), ctx) > 50


def test_line_movement_penalty_when_market_moves_against_us():
    ctx = ScoringContext(
        weights=ScoringWeights(),
        score_threshold=65.0,
        line_movement={"e": {"opened_line": 5.5, "current_line": 5.0, "side": "over"}},
    )
    assert line_movement_sub_score(_cand(event_id="e"), ctx) < 50


def test_odds_sanity_peaks_in_typical_range():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert odds_sanity_sub_score(_cand(odds=-110), ctx) >= 90
    assert odds_sanity_sub_score(_cand(odds=+105), ctx) >= 90


def test_odds_sanity_penalty_for_heavy_favorite():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert odds_sanity_sub_score(_cand(odds=-280), ctx) < 50


def test_odds_sanity_penalty_for_longshot():
    ctx = ScoringContext(weights=ScoringWeights(), score_threshold=65.0)
    assert odds_sanity_sub_score(_cand(odds=+380), ctx) < 50


def test_model_conf_neutral_when_missing():
    assert model_confidence_sub_score(_cand(md={})) == 50.0


def test_model_conf_uses_provided_value():
    assert model_confidence_sub_score(_cand(md={"model_confidence": 0.85})) == 85.0
