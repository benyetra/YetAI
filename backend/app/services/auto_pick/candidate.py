from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
# ET wall time of the evening beat run (celery_app.py schedules it; the 11:00 run
# uses it to decide whether holding a slot back is worthwhile).
EVENING_RUN_ET = time(17, 30)


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
    # Naive UTC start time, None when unknown.
    commence_time: Optional[datetime] = None
    # US Eastern slate date of the game.
    game_date: Optional[date] = None


@dataclass
class DateRange:
    """One US Eastern slate day.

    ``start`` / ``end`` are naive UTC bounds of that ET day (start inclusive,
    end exclusive) for UTC timestamp columns; ``slate_date`` is the ET date for
    Date columns.
    """

    start: datetime
    end: datetime
    slate_date: date


def slate_window_for_date(slate_date: date) -> DateRange:
    start_et = datetime.combine(slate_date, time.min, tzinfo=EASTERN)
    end_et = datetime.combine(slate_date + timedelta(days=1), time.min, tzinfo=EASTERN)
    return DateRange(
        start=to_naive_utc(start_et),
        end=to_naive_utc(end_et),
        slate_date=slate_date,
    )


def same_line(current: Optional[float], projected: Optional[float]) -> bool:
    """True when the live game-lines line is still the one the edge was computed on."""
    return (
        current is not None
        and projected is not None
        and abs(float(current) - float(projected)) <= 0.01
    )


def moved_line_edge(
    kind: str,
    side: str,
    projected: Optional[float],
    line: Optional[float],
    threshold: float,
    strict: bool = False,
) -> Optional[float]:
    """Raw projector edge against the CURRENT line, or None to drop the candidate.

    ``kind`` is "spread" (projected home margin, ``line`` = home spread) or "total".
    The raw edge is positive for home / over, as the projectors store it. Returns
    None when the stored projection is missing, the side flipped, or the pick-side
    edge no longer meets the projector's own play ``threshold`` (``>=``, or ``>`` when
    ``strict``, as WNBA totals compare).
    """
    if projected is None or line is None:
        return None
    raw = (
        float(projected) + float(line)
        if kind == "spread"
        else float(projected) - float(line)
    )
    edge = raw if side in ("home", "over") else -raw
    return raw if (edge > threshold if strict else edge >= threshold) else None


def projection_ref(row, **keys) -> dict:
    """Pointer back to the projection row a candidate was built from.

    ``keys`` are the columns that identify the row if the ETL rewrites it.
    """
    return {
        "table": getattr(row.__class__, "__tablename__", None),
        "id": getattr(row, "id", None),
        **keys,
    }


def slate_window(now_utc: datetime) -> DateRange:
    """ET slate day containing ``now_utc`` (naive UTC or aware)."""
    return slate_window_for_date(utc_to_eastern(now_utc).date())


def to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Aware -> naive UTC; naive values are assumed to already be UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def eastern_naive_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Naive US Eastern wall time -> naive UTC (aware values are converted as-is)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    return to_naive_utc(dt)


def utc_to_eastern(dt: datetime) -> datetime:
    """Naive UTC (or aware) -> aware US Eastern."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(EASTERN)


@runtime_checkable
class CandidateProvider(Protocol):
    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]: ...
