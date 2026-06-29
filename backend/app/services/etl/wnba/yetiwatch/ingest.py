"""Gather and normalize candidate news items for YetiWatch synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.etl.wnba._espn import fetch_injuries
from app.services.etl.wnba.yetiwatch.models import SourceTier


@dataclass(frozen=True)
class CandidateItem:
    tier: SourceTier
    source_label: str
    item_ts: datetime
    text: str
    player_name: str | None = None
    team_name: str | None = None


def _injury_text(status: str, injury_type: str | None) -> str:
    parts = [status]
    if injury_type:
        parts.append(f"({injury_type})")
    return " ".join(parts)


def fetch_candidate_items() -> tuple[list[CandidateItem], bool]:
    """Pull ESPN WNBA injuries as tier-official candidate items."""
    rows, fetch_ok = fetch_injuries()
    if not fetch_ok:
        return [], False

    now = datetime.utcnow()
    items: list[CandidateItem] = []
    for row in rows:
        name = (row.get("player_name") or "").strip()
        if not name:
            continue
        status = row.get("status") or "Out"
        injury_type = row.get("injury_type")
        items.append(
            CandidateItem(
                tier=SourceTier.OFFICIAL,
                source_label="ESPN WNBA injuries",
                item_ts=now,
                text=_injury_text(status, injury_type),
                player_name=name,
                team_name=row.get("team_name"),
            )
        )
    return items, True


def items_for_player(
    all_items: list[CandidateItem],
    *,
    player_name: str,
    team_name: str | None = None,
) -> list[CandidateItem]:
    """Filter candidate items relevant to a slate player."""
    name_key = player_name.strip().lower()
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


def dedupe_items(items: list[CandidateItem]) -> list[CandidateItem]:
    """Drop near-identical items (same tier + text)."""
    seen: set[tuple[str, str]] = set()
    out: list[CandidateItem] = []
    for item in items:
        key = (item.tier.value, item.text.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
