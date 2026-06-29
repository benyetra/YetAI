"""WNBA YetiWatch ingest — re-export shared package."""

from app.services.etl.yetiwatch.ingest import (
    CandidateItem,
    dedupe_items,
    items_for_subject,
)

items_for_player = items_for_subject

from app.services.etl.wnba._espn import fetch_injuries


def fetch_candidate_items():
    """Pull ESPN WNBA injuries as tier-official candidate items."""
    from datetime import datetime

    from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier

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
        text = status
        if injury_type:
            text = f"{status} ({injury_type})"
        items.append(
            CandidateItem(
                tier=SourceTier.OFFICIAL,
                source_label="ESPN WNBA injuries",
                item_ts=now,
                text=text,
                player_name=name,
                team_name=row.get("team_name"),
            )
        )
    return items, True


__all__ = [
    "CandidateItem",
    "dedupe_items",
    "fetch_candidate_items",
    "items_for_player",
]
