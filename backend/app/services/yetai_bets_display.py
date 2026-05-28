"""Subscriber-facing labels for YetAI bet API responses."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from app.models.database_models import YetAIBet

_PROP_LINE_RE = re.compile(r"\b(under|over)\b", re.I)


def title_looks_like_prop_line(title: str) -> bool:
    t = (title or "").strip()
    return bool(_PROP_LINE_RE.search(t)) and bool(re.search(r"\d", t))


def _bet_type_value(bet_type: Any) -> str:
    if bet_type is None:
        return ""
    return str(getattr(bet_type, "value", bet_type)).lower()


def _opponent_from_metadata(metadata: Optional[Mapping[str, Any]]) -> str:
    if not metadata:
        return ""
    for key in ("opponent", "opponent_team_name"):
        value = (metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _team_from_metadata(metadata: Optional[Mapping[str, Any]]) -> str:
    if not metadata:
        return ""
    for key in ("team", "team_name"):
        value = (metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def game_label_for_matchup(
    *,
    away_team: Optional[str] = None,
    home_team: Optional[str] = None,
    title: Optional[str] = None,
    sport: Optional[str] = None,
    bet_type: Any = None,
    projection_metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    """Build API ``game`` / frontend ``matchup`` (never the raw prop line)."""
    away = (away_team or "").strip()
    home = (home_team or "").strip()
    if away and home:
        return f"{away} @ {home}"

    team = _team_from_metadata(projection_metadata)
    opponent = _opponent_from_metadata(projection_metadata)
    if team and opponent:
        return f"{team} @ {opponent}"
    if opponent:
        return f"vs {opponent}"

    title_text = (title or "").strip()
    if title_text and not title_looks_like_prop_line(title_text):
        return title_text

    if _bet_type_value(bet_type) == "prop":
        sport_text = (sport or "").strip()
        return f"{sport_text} player prop".strip() if sport_text else "Player prop"

    return "Matchup pending"


def subscriber_game_label(bet: "YetAIBet") -> str:
    """Value for API ``game`` / frontend ``matchup`` (never the raw prop line)."""
    pf = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    md = pf.get("projection_metadata")
    metadata = md if isinstance(md, dict) else None

    return game_label_for_matchup(
        away_team=bet.away_team,
        home_team=bet.home_team,
        title=bet.title,
        sport=bet.sport,
        bet_type=bet.bet_type,
        projection_metadata=metadata,
    )
