from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable


class MarketType(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PLAYER_PROP = "player_prop"


@dataclass
class BetCandidate:
    market_type: MarketType
    league: str
    event_id: str
    selection: str
    market_line: float
    market_odds: int
    our_projection: float
    projection_metadata: dict[str, Any] = field(default_factory=dict)
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    commence_time: Optional[datetime] = None


@dataclass
class DateRange:
    start: datetime
    end: datetime


@runtime_checkable
class CandidateProvider(Protocol):
    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]: ...
