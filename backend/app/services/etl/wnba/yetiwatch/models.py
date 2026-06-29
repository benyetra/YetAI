"""Pydantic models for YetiWatch signal payloads."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

ET = ZoneInfo("America/New_York")

_MAG_SHORT = {"low": "low", "medium": "med", "high": "high"}
_ARROW_DOWN = "\u2193"
_ARROW_UP = "\u2191"


class PlayerStatus(str, Enum):
    AVAILABLE = "available"
    PROBABLE = "probable"
    QUESTIONABLE = "questionable"
    DOUBTFUL = "doubtful"
    OUT = "out"
    GAME_TIME_DECISION = "game_time_decision"
    NOT_REPORTED = "not_reported"


class UsageDelta(str, Enum):
    STRONG_DECREASE = "strong_decrease"
    DECREASE = "decrease"
    NEUTRAL = "neutral"
    INCREASE = "increase"
    STRONG_INCREASE = "strong_increase"


class RoleSlot(str, Enum):
    STARTER = "starter"
    BENCH = "bench"
    OUT_OF_ROTATION = "out_of_rotation"
    DNP = "dnp"
    UNKNOWN = "unknown"


class SignalType(str, Enum):
    REST_LOAD_MANAGEMENT = "rest_load_management"
    INJURY_STATUS_CHANGE = "injury_status_change"
    MINUTES_RESTRICTION = "minutes_restriction"
    USAGE_INCREASE = "usage_increase"
    ROTATION_CHANGE = "rotation_change"
    TEAMMATE_AVAILABILITY = "teammate_availability"
    NATIONAL_TEAM_OVERSEAS = "national_team_overseas"
    BLOWOUT_PACE_RISK = "blowout_pace_risk"
    FOUL_TROUBLE_EJECTION = "foul_trouble_ejection"
    TRADE_ROSTER_MOVE = "trade_roster_move"
    COACHING_SCHEME_CHANGE = "coaching_scheme_change"


class ImpactDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class ImpactMagnitude(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Corroboration(str, Enum):
    SINGLE = "single"
    CORROBORATED = "corroborated"
    CONFLICTING = "conflicting"


class SourceTier(str, Enum):
    OFFICIAL = "official"
    BEAT_WRITER = "beat_writer"
    AGGREGATOR = "aggregator"
    COMMUNITY = "community"


class MinutesOutlook(BaseModel):
    cap_min: float | None = None
    delta_min: float | None = None
    note: str | None = None


class RoleChange(BaseModel):
    from_role: RoleSlot = Field(alias="from")
    to_role: RoleSlot = Field(alias="to")

    model_config = {"populate_by_name": True}


class Impact(BaseModel):
    direction: ImpactDirection
    magnitude: ImpactMagnitude
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None


class RelatedSubject(BaseModel):
    player_id: str
    relation: Literal[
        "teammate_out_raises_usage",
        "teammate_back_lowers_usage",
        "competes_for_minutes",
        "other",
    ]


class Provenance(BaseModel):
    source_count: int = Field(ge=0)
    corroboration: Corroboration
    source_tiers: list[SourceTier] | None = None
    latest_source_ts: datetime | None = None


class YetiWatchSignalPayload(BaseModel):
    run_id: str
    as_of: datetime
    player_id: str
    player_name: str | None = None
    team_id: str | None = None
    game_id: str
    opponent_id: str | None = None
    game_start: datetime | None = None
    status: PlayerStatus
    availability_prob: float | None = Field(default=None, ge=0, le=1)
    minutes_outlook: MinutesOutlook | None = None
    usage_delta: UsageDelta = UsageDelta.NEUTRAL
    usage_delta_factor: float | None = None
    role_change: RoleChange | None = None
    signal_types: list[SignalType] = Field(default_factory=list)
    impact: Impact
    related_subjects: list[RelatedSubject] = Field(default_factory=list)
    news_string: str = Field(max_length=160)
    provenance: Provenance

    @field_validator("news_string")
    @classmethod
    def _news_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("news_string must not be blank")
        return value


def format_as_of_et(dt: datetime) -> str:
    """Short local clock for news_string, e.g. '5:40p ET'."""
    local = (
        dt.astimezone(ET)
        if dt.tzinfo
        else dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
    )
    hour = local.hour % 12 or 12
    minute = local.minute
    suffix = "a" if local.hour < 12 else "p"
    if minute:
        return f"{hour}:{minute:02d}{suffix} ET"
    return f"{hour}{suffix} ET"


def format_impact_tag(direction: ImpactDirection, magnitude: ImpactMagnitude) -> str:
    mag = _MAG_SHORT.get(magnitude.value, magnitude.value)
    if direction == ImpactDirection.DOWN:
        return f"[prod {_ARROW_DOWN} {mag}]"
    if direction == ImpactDirection.UP:
        return f"[prod {_ARROW_UP} {mag}]"
    if direction == ImpactDirection.UNKNOWN:
        return "[unknown]"
    return "[neutral]"


def build_news_string(
    summary: str,
    *,
    as_of: datetime,
    direction: ImpactDirection,
    magnitude: ImpactMagnitude,
) -> str:
    tag = format_impact_tag(direction, magnitude)
    clock = format_as_of_et(as_of)
    return f"{summary.strip()} {tag} {clock}"[:160]


def make_game_id(game_date: date, team_id: int, opponent_id: int | None) -> str:
    opp = opponent_id if opponent_id is not None else 0
    return f"wnba_game_{game_date.isoformat().replace('-', '_')}_{team_id}_{opp}"


def build_neutral_payload(
    *,
    run_id: str,
    as_of: datetime,
    player_id: int,
    player_name: str,
    team_id: int,
    game_date: date,
    opponent_id: int | None,
    game_start: datetime | None = None,
    home_game: bool | None = None,
) -> YetiWatchSignalPayload:
    """Explicit neutral state when no material candidate items exist."""
    news = build_news_string(
        "No material news.",
        as_of=as_of,
        direction=ImpactDirection.NEUTRAL,
        magnitude=ImpactMagnitude.LOW,
    )
    return YetiWatchSignalPayload(
        run_id=run_id,
        as_of=as_of,
        player_id=str(player_id),
        player_name=player_name,
        team_id=str(team_id),
        game_id=make_game_id(game_date, team_id, opponent_id),
        opponent_id=str(opponent_id) if opponent_id is not None else None,
        game_start=game_start,
        status=PlayerStatus.NOT_REPORTED,
        availability_prob=None,
        minutes_outlook=MinutesOutlook(),
        usage_delta=UsageDelta.NEUTRAL,
        role_change=RoleChange(from_role=RoleSlot.UNKNOWN, to_role=RoleSlot.UNKNOWN),
        signal_types=[],
        impact=Impact(
            direction=ImpactDirection.NEUTRAL,
            magnitude=ImpactMagnitude.LOW,
            confidence=0.5,
            rationale=None,
        ),
        news_string=news,
        provenance=Provenance(
            source_count=0,
            corroboration=Corroboration.SINGLE,
            source_tiers=[],
        ),
    )
