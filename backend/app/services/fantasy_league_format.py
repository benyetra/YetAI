"""Derive league-format multipliers (superflex, 2QB, TE premium) from Sleeper docs."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Shared constants — keep in sync with frontend/src/lib/fantasy-trade-value.ts
QB_PREMIUM_SUPERFLEX = 1.4
QB_PREMIUM_2QB = 1.25
TE_SCARCITY_LARGE_LEAGUE = 1.05
TE_SCARCITY_LARGE_WITH_PREMIUM = 1.08

# Sleeper league settings.type: 0=redraft, 1=keeper, 2=dynasty
SLEEPER_REDRAFT_TYPE = 0
SLEEPER_KEEPER_TYPE = 1
SLEEPER_DYNASTY_TYPE = 2

_BENCH_SLOTS = frozenset({"BN", "IR"})
_SUPERFLEX_SLOTS = frozenset({"SUPER_FLEX", "SUPERFLEX"})


def sleeper_settings_type(league: Optional[Dict[str, Any]]) -> int:
    """Return Sleeper ``settings.type`` (0 redraft, 1 keeper, 2 dynasty)."""
    if not league:
        return SLEEPER_REDRAFT_TYPE
    settings = league.get("settings") or {}
    try:
        return int(settings.get("type", SLEEPER_REDRAFT_TYPE))
    except (TypeError, ValueError):
        return SLEEPER_REDRAFT_TYPE


def format_type_from_sleeper_type(settings_type: int) -> str:
    if settings_type == SLEEPER_DYNASTY_TYPE:
        return "dynasty"
    if settings_type == SLEEPER_KEEPER_TYPE:
        return "keeper"
    return "redraft"


def league_format_flags_from_sleeper(
    league: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Dynasty / keeper / redraft flags from a Sleeper league document."""
    settings_type = sleeper_settings_type(league)
    format_type = format_type_from_sleeper_type(settings_type)
    return {
        "format_type": format_type,
        "is_dynasty": format_type == "dynasty",
        "is_keeper": format_type == "keeper",
        "is_redraft": format_type == "redraft",
        "sleeper_settings_type": settings_type,
    }


def is_dynasty_league(league: Optional[Dict[str, Any]]) -> bool:
    return league_format_flags_from_sleeper(league)["is_dynasty"]


def age_multiplier_for_format(age: int, *, is_dynasty: bool = False) -> float:
    """Age curve for trade values — steeper youth premium in dynasty."""
    if is_dynasty:
        if age <= 22:
            return 1.25
        if age <= 24:
            return 1.15
        if age <= 27:
            return 1.0
        if age <= 30:
            return 0.9
        return 0.65
    if age <= 24:
        return 1.1
    if age <= 27:
        return 1.0
    if age <= 30:
        return 0.95
    return 0.8


def _starter_positions(league: Dict[str, Any]) -> list[str]:
    positions = league.get("roster_positions") or []
    return [
        str(pos).upper() for pos in positions if str(pos).upper() not in _BENCH_SLOTS
    ]


def _te_premium_from_scoring(scoring_settings: Dict[str, Any]) -> float:
    for key in ("bonus_rec_te", "rec_te"):
        raw = scoring_settings.get(key)
        if raw is not None:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return 0.0


def league_format_from_sleeper(league: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive trade-value league format from a Sleeper league document."""
    if not league:
        return {
            "has_superflex": False,
            "is_2qb": False,
            "qb_premium_multiplier": 1.0,
            "te_premium": 0.0,
            "team_count": 12,
            "te_scarcity_multiplier": 1.0,
            **league_format_flags_from_sleeper(None),
        }

    starters = _starter_positions(league)
    has_superflex = any(pos in _SUPERFLEX_SLOTS for pos in starters)
    qb_starter_count = sum(1 for pos in starters if pos == "QB")
    is_2qb = qb_starter_count >= 2

    if has_superflex:
        qb_premium_multiplier = QB_PREMIUM_SUPERFLEX
    elif is_2qb:
        qb_premium_multiplier = QB_PREMIUM_2QB
    else:
        qb_premium_multiplier = 1.0

    scoring_settings = league.get("scoring_settings") or {}
    te_premium = _te_premium_from_scoring(scoring_settings)

    settings = league.get("settings") or {}
    team_count = int(
        settings.get("num_teams")
        or league.get("total_rosters")
        or league.get("teams_count")
        or 12
    )

    if team_count >= 12 and te_premium > 0:
        te_scarcity_multiplier = TE_SCARCITY_LARGE_WITH_PREMIUM
    elif team_count >= 12:
        te_scarcity_multiplier = TE_SCARCITY_LARGE_LEAGUE
    else:
        te_scarcity_multiplier = 1.0

    format_flags = league_format_flags_from_sleeper(league)

    return {
        "has_superflex": has_superflex,
        "is_2qb": is_2qb,
        "qb_premium_multiplier": qb_premium_multiplier,
        "te_premium": te_premium,
        "team_count": team_count,
        "te_scarcity_multiplier": te_scarcity_multiplier,
        **format_flags,
    }


def format_multiplier(position: str, league_format: Dict[str, Any]) -> float:
    """Position-specific trade-value multiplier for league format."""
    pos = str(position or "").upper()
    if not league_format:
        return 1.0

    has_superflex = bool(league_format.get("has_superflex"))
    is_2qb = bool(league_format.get("is_2qb"))
    te_premium = float(league_format.get("te_premium") or 0)
    te_scarcity = float(league_format.get("te_scarcity_multiplier") or 1.0)
    team_count = int(league_format.get("team_count") or 12)

    if pos == "QB" and (has_superflex or is_2qb):
        return float(league_format.get("qb_premium_multiplier") or 1.0)

    if pos == "TE":
        mult = te_scarcity if team_count >= 12 else 1.0
        if te_premium > 0:
            mult += te_premium
        return mult

    return 1.0
