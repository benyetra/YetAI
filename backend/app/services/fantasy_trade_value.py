"""
Deterministic fantasy trade values (no randomness).

Shared by trade analyzer API routes and ``trade_analyzer_service``.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

_POSITION_RANGES: Dict[str, tuple[float, float]] = {
    "QB": (20.0, 45.0),
    "RB": (15.0, 40.0),
    "WR": (12.0, 38.0),
    "TE": (8.0, 25.0),
    "K": (2.0, 6.0),
    "DEF": (3.0, 8.0),
}

_STRONG_OFFENSES = frozenset({"KC", "BUF", "DAL", "SF", "PHI", "MIA", "LAR"})
_WEAK_OFFENSES = frozenset({"WAS", "CHI", "NYG", "CAR"})


def stable_unit(seed: str) -> float:
    """Map *seed* to a stable float in [0, 1)."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _age_multiplier(age: int) -> float:
    if age <= 24:
        return 1.1
    if age <= 27:
        return 1.0
    if age <= 30:
        return 0.95
    return 0.8


def _team_multiplier(team: str) -> float:
    if team in _STRONG_OFFENSES:
        return 1.05
    if team in _WEAK_OFFENSES:
        return 0.95
    return 1.0


def _scoring_multiplier(position: str, scoring_type: str) -> float:
    scoring = (scoring_type or "standard").lower().replace("-", "_")
    if position in {"WR", "TE"}:
        if scoring == "ppr":
            return 1.15
        if scoring in {"half_ppr", "half"}:
            return 1.08
    if position == "RB" and scoring == "standard":
        return 1.1
    return 1.0


def calculate_deterministic_trade_value(
    player: Dict[str, Any],
    *,
    scoring_type: str = "standard",
) -> float:
    """Stable trade value from Sleeper-style player metadata."""
    position = str(player.get("position") or "UNKNOWN").upper()
    age = int(player.get("age") or 27)
    team = str(player.get("team") or "")
    player_key = str(
        player.get("id")
        or player.get("player_id")
        or player.get("name")
        or player.get("full_name")
        or "unknown"
    )

    min_val, max_val = _POSITION_RANGES.get(position, (8.0, 15.0))
    seed = f"{player_key}:{position}:{age}:{team}:{scoring_type}"
    unit = stable_unit(seed)
    base_value = min_val + unit * (max_val - min_val)

    value = (
        base_value
        * _age_multiplier(age)
        * _team_multiplier(team)
        * _scoring_multiplier(position, scoring_type)
    )
    return round(value, 1)


def select_trade_partner(
    teams: List[Dict[str, Any]],
    *,
    seed: str = "",
) -> Optional[Dict[str, Any]]:
    """Pick a stable trade partner from *teams* using *seed*."""
    if not teams:
        return None
    ordered = sorted(teams, key=lambda team: str(team.get("team_id", "")))
    idx = int(stable_unit(seed or "trade_partner") * len(ordered)) % len(ordered)
    return ordered[idx]
