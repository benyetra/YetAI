from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.confidence_score import ConfidenceScore


def test_scoring_weights_defaults_sum_to_one():
    w = ScoringWeights()
    total = (w.edge + w.historical + w.freshness +
             w.line_movement + w.odds_sanity + w.model_conf)
    assert abs(total - 1.0) < 1e-6


def test_scoring_context_holds_lookup_tables():
    ctx = ScoringContext(
        weights=ScoringWeights(),
        score_threshold=65.0,
        historical_hit_rates={("player_prop", "MLB"): 0.61},
        line_movement={"event-1": {"opened": -110, "current": -125}},
        now=None,
    )
    assert ctx.historical_hit_rates[("player_prop", "MLB")] == 0.61


def test_confidence_score_dataclass():
    s = ConfidenceScore(total=72.5, breakdown={"edge": 38.0}, reasoning="strong edge")
    assert s.total == 72.5
    assert s.breakdown["edge"] == 38.0
