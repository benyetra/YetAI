"""Rule-based synthesis when Bedrock is disabled or for deterministic tests."""

from __future__ import annotations

from datetime import datetime

from app.services.etl.yetiwatch.ingest import CandidateItem
from app.services.etl.yetiwatch.models import (
    Corroboration,
    Impact,
    ImpactDirection,
    ImpactMagnitude,
    MinutesOutlook,
    PlayerStatus,
    Provenance,
    RoleChange,
    RoleSlot,
    SignalType,
    SourceTier,
    UsageDelta,
    YetiWatchSignalPayload,
    build_neutral_payload,
    build_news_string,
    make_game_id,
)

_ESPN_STATUS_TO_PLAYER_STATUS: dict[str, PlayerStatus] = {
    "out": PlayerStatus.OUT,
    "questionable": PlayerStatus.QUESTIONABLE,
    "doubtful": PlayerStatus.DOUBTFUL,
    "probable": PlayerStatus.PROBABLE,
    "day-to-day": PlayerStatus.QUESTIONABLE,
    "injured reserve": PlayerStatus.OUT,
    "ir": PlayerStatus.OUT,
}


def _status_from_text(text: str) -> PlayerStatus:
    lower = text.lower()
    for key, status in _ESPN_STATUS_TO_PLAYER_STATUS.items():
        if key in lower:
            return status
    return PlayerStatus.NOT_REPORTED


def _impact_for_status(
    status: PlayerStatus,
) -> tuple[ImpactDirection, ImpactMagnitude, float]:
    if status == PlayerStatus.OUT:
        return ImpactDirection.DOWN, ImpactMagnitude.HIGH, 0.85
    if status == PlayerStatus.DOUBTFUL:
        return ImpactDirection.DOWN, ImpactMagnitude.MEDIUM, 0.7
    if status == PlayerStatus.QUESTIONABLE:
        return ImpactDirection.UNKNOWN, ImpactMagnitude.LOW, 0.45
    if status == PlayerStatus.PROBABLE:
        return ImpactDirection.NEUTRAL, ImpactMagnitude.LOW, 0.6
    return ImpactDirection.NEUTRAL, ImpactMagnitude.LOW, 0.55


def synthesize_heuristic(
    *,
    sport: str,
    run_id: str,
    as_of: datetime,
    entity_id: str | int,
    entity_name: str,
    team_id: int | str,
    game_date,
    opponent_id: int | str | None,
    items: list[CandidateItem],
    game_start: datetime | None = None,
) -> YetiWatchSignalPayload:
    if not items:
        return build_neutral_payload(
            sport=sport,
            run_id=run_id,
            as_of=as_of,
            entity_id=entity_id,
            player_name=entity_name,
            team_id=team_id,
            game_date=game_date,
            opponent_id=opponent_id,
            game_start=game_start,
        )

    primary = items[0]
    status = _status_from_text(primary.text)
    direction, magnitude, confidence = _impact_for_status(status)
    signal_types: list[SignalType] = []
    if status in {PlayerStatus.OUT, PlayerStatus.DOUBTFUL, PlayerStatus.QUESTIONABLE}:
        signal_types.append(SignalType.INJURY_STATUS_CHANGE)
    if "rest" in primary.text.lower():
        signal_types.append(SignalType.REST_LOAD_MANAGEMENT)

    summary_parts = []
    if status == PlayerStatus.OUT:
        summary_parts.append("Listed out on injury report")
    elif status == PlayerStatus.QUESTIONABLE:
        summary_parts.append("Questionable on injury report")
    elif status == PlayerStatus.DOUBTFUL:
        summary_parts.append("Doubtful on injury report")
    else:
        summary_parts.append("Injury report noted; monitor status")
    summary = "; ".join(summary_parts)

    news_string = build_news_string(
        summary,
        as_of=as_of,
        direction=direction,
        magnitude=magnitude,
    )
    tiers = list({item.tier for item in items})
    return YetiWatchSignalPayload(
        run_id=run_id,
        as_of=as_of,
        player_id=str(entity_id),
        player_name=entity_name,
        team_id=str(team_id),
        game_id=make_game_id(sport, game_date, team_id, opponent_id),
        opponent_id=str(opponent_id) if opponent_id is not None else None,
        game_start=game_start,
        status=status,
        availability_prob=0.2 if status == PlayerStatus.OUT else 0.55,
        minutes_outlook=MinutesOutlook(),
        usage_delta=UsageDelta.NEUTRAL,
        role_change=RoleChange(from_role=RoleSlot.UNKNOWN, to_role=RoleSlot.UNKNOWN),
        signal_types=signal_types,
        impact=Impact(
            direction=direction,
            magnitude=magnitude,
            confidence=confidence,
            rationale=summary,
        ),
        news_string=news_string,
        provenance=Provenance(
            source_count=len(items),
            corroboration=(
                Corroboration.CORROBORATED if len(items) > 1 else Corroboration.SINGLE
            ),
            source_tiers=tiers or [SourceTier.OFFICIAL],
            latest_source_ts=items[0].item_ts,
        ),
    )
