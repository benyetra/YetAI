from dataclasses import dataclass, field


@dataclass
class ConfidenceScore:
    total: float
    breakdown: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""
