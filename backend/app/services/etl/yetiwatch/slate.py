"""Slate subjects for YetiWatch synthesis (one row per projected entity)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SlateSubject:
    sport: str
    entity_id: str
    entity_name: str
    team_id: str | None
    opponent_id: str | None
    game_date: date
    home_game: bool | None = None
    baseline_role: str = "unknown"
