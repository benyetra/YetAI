from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScoringWeights:
    edge: float = 0.40
    historical: float = 0.20
    freshness: float = 0.15
    line_movement: float = 0.10
    odds_sanity: float = 0.10
    model_conf: float = 0.05


@dataclass
class ScoringContext:
    weights: ScoringWeights
    score_threshold: float
    historical_hit_rates: dict[tuple[str, str], float] = field(default_factory=dict)
    line_movement: dict[str, dict] = field(default_factory=dict)
    now: Optional[datetime] = None
