"""Subscriber-facing labels for YetAI bet API responses."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.database_models import YetAIBet

_PROP_LINE_RE = re.compile(r"\b(under|over)\b", re.I)


def title_looks_like_prop_line(title: str) -> bool:
    t = (title or "").strip()
    return bool(_PROP_LINE_RE.search(t)) and bool(re.search(r"\d", t))


def subscriber_game_label(bet: "YetAIBet") -> str:
    """Value for API ``game`` / frontend ``matchup`` (never the raw prop line)."""
    away = (bet.away_team or "").strip()
    home = (bet.home_team or "").strip()
    if away and home:
        return f"{away} @ {home}"

    title = (bet.title or "").strip()
    if title and not title_looks_like_prop_line(title):
        return title

    return "Matchup pending"
