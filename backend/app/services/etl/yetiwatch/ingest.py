"""Multi-source candidate news items for YetiWatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.etl.yetiwatch.models import SourceTier


@dataclass(frozen=True)
class CandidateItem:
    tier: SourceTier
    source_label: str
    item_ts: datetime
    text: str
    player_name: str | None = None
    team_name: str | None = None


def dedupe_items(items: list[CandidateItem]) -> list[CandidateItem]:
    seen: set[tuple[str, str]] = set()
    out: list[CandidateItem] = []
    for item in items:
        key = (item.tier.value, item.text.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def items_for_subject(
    all_items: list[CandidateItem],
    *,
    entity_name: str,
    team_name: str | None = None,
) -> list[CandidateItem]:
    name_key = entity_name.strip().lower()
    matched = [
        item
        for item in all_items
        if item.player_name and item.player_name.strip().lower() == name_key
    ]
    if team_name and not matched:
        team_key = team_name.strip().lower()
        matched = [
            item
            for item in all_items
            if item.team_name and item.team_name.strip().lower() == team_key
        ]
    return matched
