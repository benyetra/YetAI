from datetime import datetime

from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights


def _strider():
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP, league="MLB",
        event_id="mlb-bos-nyy", selection="Strider OVER 5.5 K",
        market_line=5.5, market_odds=-115, our_projection=9.0,
        projection_metadata={"sample_size": 7, "generated_at": "2026-05-22T08:00:00",
                             "model_confidence": 0.78},
    )


def _ctx():
    return ScoringContext(
        weights=ScoringWeights(), score_threshold=65.0,
        historical_hit_rates={("player_prop", "MLB"): 0.61},
        line_movement={}, now=datetime(2026, 5, 22, 9, 0, 0),
    )


def test_scorer_returns_total_breakdown_reasoning():
    s = ConfidenceScorer().score(_strider(), _ctx())
    assert 0 <= s.total <= 100
    assert set(s.breakdown.keys()) == {
        "edge", "historical", "freshness", "line_movement", "odds_sanity", "model_conf"
    }
    assert "Strider" in s.reasoning or "5.5" in s.reasoning


def test_scorer_strider_above_threshold():
    s = ConfidenceScorer().score(_strider(), _ctx())
    assert s.total >= 65


def test_scorer_weights_applied_correctly():
    s = ConfidenceScorer().score(_strider(), _ctx())
    w = ScoringWeights()
    expected = (
        s.breakdown["edge"] * w.edge
        + s.breakdown["historical"] * w.historical
        + s.breakdown["freshness"] * w.freshness
        + s.breakdown["line_movement"] * w.line_movement
        + s.breakdown["odds_sanity"] * w.odds_sanity
        + s.breakdown["model_conf"] * w.model_conf
    )
    assert abs(s.total - expected) < 0.01
