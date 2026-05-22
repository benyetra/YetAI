from dataclasses import dataclass
from typing import Optional

from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate
from app.services.auto_pick.confidence_score import ConfidenceScore


@dataclass
class ScoredCandidate:
    candidate: BetCandidate
    score: ConfidenceScore
    tier: Optional[SubscriptionTier] = None
    drop_reason: Optional[str] = None


@dataclass
class SelectorConfig:
    threshold: float = 65.0
    odds_min: int = -300
    odds_max: int = 400
    max_picks: int = 4


_TIER_BY_RANK = [
    SubscriptionTier.FREE,
    SubscriptionTier.PRO,
    SubscriptionTier.PRO,
    SubscriptionTier.ELITE,
]


class BetSelector:
    def __init__(self, config: SelectorConfig):
        self.config = config

    def select(self, scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
        eligible = []
        for sc in scored:
            if sc.score.total < self.config.threshold:
                sc.drop_reason = f"below_threshold:{sc.score.total:.1f}"
                continue
            o = sc.candidate.market_odds
            if o < self.config.odds_min or o > self.config.odds_max:
                sc.drop_reason = f"odds_out_of_bounds:{o}"
                continue
            eligible.append(sc)

        eligible.sort(key=lambda s: s.score.total, reverse=True)

        picks: list[ScoredCandidate] = []
        used_events: set[str] = set()
        for sc in eligible:
            if sc.candidate.event_id in used_events:
                sc.drop_reason = "correlation_same_event"
                continue
            picks.append(sc)
            used_events.add(sc.candidate.event_id)
            if len(picks) >= self.config.max_picks:
                break

        for i, p in enumerate(picks):
            p.tier = _TIER_BY_RANK[min(i, len(_TIER_BY_RANK) - 1)]
        return picks
