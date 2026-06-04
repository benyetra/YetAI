from dataclasses import dataclass
from typing import Optional

from app.models.database_models import SubscriptionTier
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.parlay_utils import (
    combine_parlay_odds,
    meets_parlay_odds_target,
)
from app.services.auto_pick.selector import ScoredCandidate, SelectorConfig
from app.services.mlb_hit_pick import MIN_PARLAY_COMBINED_ODDS


@dataclass
class ScoredParlayPick:
    legs: tuple[ScoredCandidate, ScoredCandidate]
    combined_odds: int
    score: ConfidenceScore
    tier: Optional[SubscriptionTier] = None
    drop_reason: Optional[str] = None


def _is_parlay_eligible(sc: ScoredCandidate, threshold: float) -> bool:
    if sc.score.total < threshold:
        return False
    md = sc.candidate.projection_metadata or {}
    if not md.get("parlay_eligible"):
        return False
    return md.get("stat") == "hits"


def _parlay_confidence(
    leg_a: ScoredCandidate, leg_b: ScoredCandidate
) -> ConfidenceScore:
    leg_scores = sorted([leg_a.score.total, leg_b.score.total])
    total = round(min(leg_scores[0], leg_scores[1] * 0.95), 1)
    breakdown = {
        "leg_a_score": round(leg_a.score.total, 1),
        "leg_b_score": round(leg_b.score.total, 1),
        "strategy": "mlb_2leg_hits",
    }
    reasoning = (
        f"2-leg MLB hit parlay. Leg 1: {leg_a.candidate.selection} "
        f"(confidence {leg_a.score.total:.0f}). "
        f"Leg 2: {leg_b.candidate.selection} "
        f"(confidence {leg_b.score.total:.0f}). "
        f"Parlay confidence {total:.0f} (conservative min-leg blend)."
    )
    return ConfidenceScore(total=total, breakdown=breakdown, reasoning=reasoning)


class ParlaySelector:
    """Build at most one 2-leg hit parlay when combined odds are better than -125."""

    def __init__(self, config: SelectorConfig):
        self.config = config

    def select_parlay(
        self, scored: list[ScoredCandidate]
    ) -> Optional[ScoredParlayPick]:
        eligible = [
            sc for sc in scored if _is_parlay_eligible(sc, self.config.threshold)
        ]
        if len(eligible) < 2:
            return None

        best: Optional[ScoredParlayPick] = None
        for i, leg_a in enumerate(eligible):
            for leg_b in eligible[i + 1 :]:
                if leg_a.candidate.event_id == leg_b.candidate.event_id:
                    continue
                combined = combine_parlay_odds(
                    [leg_a.candidate.market_odds, leg_b.candidate.market_odds]
                )
                if not meets_parlay_odds_target(combined, MIN_PARLAY_COMBINED_ODDS):
                    continue

                score = _parlay_confidence(leg_a, leg_b)
                candidate = ScoredParlayPick(
                    legs=(leg_a, leg_b),
                    combined_odds=combined,
                    score=score,
                )
                if best is None or candidate.score.total > best.score.total:
                    best = candidate

        if best is not None:
            best.tier = SubscriptionTier.PRO
        return best
