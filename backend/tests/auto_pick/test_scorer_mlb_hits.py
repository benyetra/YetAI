"""MLB hits auto-pick scoring alignment with hits board."""

from datetime import datetime

from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.mlb_hit_pick import (
    hit_confidence_pct,
    projection_from_combined_score,
)


def _hits_candidate(combined_score: float) -> BetCandidate:
    proj = projection_from_combined_score(combined_score)
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id=f"hit-{combined_score}",
        selection="Player OVER 0.5 hits",
        market_line=0.5,
        market_odds=-110,
        our_projection=proj,
        projection_metadata={
            "stat": "hits",
            "side": "over",
            "combined_score": combined_score,
            "sample_size": 8,
            "generated_at": "2026-06-09",
            "model_confidence": hit_confidence_pct(combined_score) / 100.0,
        },
    )


def test_hits_board_score_2_5_reaches_straight_pick_threshold():
    ctx = ScoringContext(
        weights=ScoringWeights(), score_threshold=65.0, now=datetime(2026, 6, 9, 13)
    )
    score = ConfidenceScorer().score(_hits_candidate(2.5), ctx)
    assert score.total >= 65.0


def test_hits_board_score_2_0_still_below_threshold():
    ctx = ScoringContext(
        weights=ScoringWeights(), score_threshold=65.0, now=datetime(2026, 6, 9, 13)
    )
    score = ConfidenceScorer().score(_hits_candidate(2.0), ctx)
    assert score.total < 65.0
