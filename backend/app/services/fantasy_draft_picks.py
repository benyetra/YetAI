"""Sleeper draft pick resolution for trade analyzer (dynasty + redraft)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Sleeper league settings.type: 0=redraft, 1=keeper, 2=dynasty
_DYNASTY_TYPE = 2


def stable_pick_id(season: int, round_number: int, pick_slot_roster_id: int) -> int:
    """Deterministic pick id from season/round/original roster slot (stable when traded)."""
    pick_key = f"{season}-{round_number}-{pick_slot_roster_id}"
    return abs(hash(pick_key)) % 2147483647


def calculate_draft_pick_trade_value(
    season: int,
    round_number: int,
    *,
    is_dynasty: bool = False,
) -> float:
    base_values = {1: 35.0, 2: 18.0, 3: 8.0, 4: 4.0}
    base_value = base_values.get(round_number, 2.0)
    if is_dynasty:
        base_value *= 1.3
    years_out = season - datetime.now().year
    if years_out > 0:
        base_value *= 0.9**years_out
    elif years_out < 0:
        base_value *= 0.5
    return round(base_value, 1)


def calculate_faab_trade_value(faab_amount: int) -> float:
    if faab_amount <= 0:
        return 0.0
    return round(faab_amount * 0.7, 1)


def _league_is_dynasty(league: Dict[str, Any]) -> bool:
    settings = league.get("settings") or {}
    return int(settings.get("type", 0)) == _DYNASTY_TYPE


def _pick_slot_id(pick: Dict[str, Any]) -> int:
    return int(pick.get("roster_id") or pick.get("owner_id") or 0)


def _pick_owner_id(pick: Dict[str, Any]) -> int:
    return int(pick.get("owner_id") or pick.get("roster_id") or 0)


def infer_redraft_default_picks(league: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Assign each roster slot a full set of next-season picks (redraft/keeper)."""
    settings = league.get("settings") or {}
    draft_rounds = int(settings.get("draft_rounds") or 3)
    total_rosters = int(league.get("total_rosters") or 12)
    season = int(league.get("season") or datetime.now().year)
    next_season = season + 1

    picks: List[Dict[str, Any]] = []
    for slot_id in range(1, total_rosters + 1):
        for round_num in range(1, draft_rounds + 1):
            picks.append(
                {
                    "season": str(next_season),
                    "round": round_num,
                    "roster_id": slot_id,
                    "owner_id": slot_id,
                    "previous_owner_id": slot_id,
                }
            )
    return picks


def merge_traded_and_default_picks(
    league: Dict[str, Any],
    traded_picks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if _league_is_dynasty(league):
        return list(traded_picks or [])

    merged: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
    for pick in infer_redraft_default_picks(league):
        season = int(pick.get("season") or datetime.now().year)
        round_num = int(pick.get("round") or 1)
        slot_id = _pick_slot_id(pick)
        merged[(season, round_num, slot_id)] = pick

    for pick in traded_picks or []:
        season = int(pick.get("season") or datetime.now().year)
        round_num = int(pick.get("round") or 1)
        slot_id = _pick_slot_id(pick)
        merged[(season, round_num, slot_id)] = pick

    return list(merged.values())


def format_pick_record(
    pick: Dict[str, Any],
    *,
    is_dynasty: bool,
) -> Dict[str, Any]:
    slot_id = _pick_slot_id(pick)
    owner_id = _pick_owner_id(pick)
    season = int(pick.get("season") or datetime.now().year)
    round_num = int(pick.get("round") or 1)
    pick_id = stable_pick_id(season, round_num, slot_id)

    return {
        "pick_id": pick_id,
        "season": season,
        "round": round_num,
        "description": f"{season} Round {round_num} Pick",
        "trade_value": calculate_draft_pick_trade_value(
            season, round_num, is_dynasty=is_dynasty
        ),
        "roster_id": owner_id,
        "pick_slot": slot_id,
        "previous_owner_id": pick.get("previous_owner_id"),
    }


def format_roster_tradeable_picks(
    league: Dict[str, Any],
    traded_picks: List[Dict[str, Any]],
    roster_id: int,
) -> List[Dict[str, Any]]:
    is_dynasty = _league_is_dynasty(league)
    all_picks = merge_traded_and_default_picks(league, traded_picks)
    formatted: List[Dict[str, Any]] = []

    for pick in all_picks:
        if _pick_owner_id(pick) != int(roster_id):
            continue
        formatted.append(format_pick_record(pick, is_dynasty=is_dynasty))

    formatted.sort(key=lambda p: (p["season"], p["round"]))
    return formatted


def build_league_pick_registry(
    league: Dict[str, Any],
    traded_picks: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    is_dynasty = _league_is_dynasty(league)
    registry: Dict[int, Dict[str, Any]] = {}
    for pick in merge_traded_and_default_picks(league, traded_picks):
        record = format_pick_record(pick, is_dynasty=is_dynasty)
        registry[int(record["pick_id"])] = record
    return registry


def lookup_pick_trade_value(
    pick_id: int,
    pick_registry: Optional[Dict[int, Dict[str, Any]]],
) -> float:
    if not pick_registry:
        return 0.0
    meta = pick_registry.get(int(pick_id))
    if not meta:
        return 0.0
    return float(meta.get("trade_value") or 0.0)


def pick_owned_by_roster(
    pick_id: int,
    roster_id: int,
    pick_registry: Optional[Dict[int, Dict[str, Any]]],
) -> bool:
    if not pick_registry:
        return False
    meta = pick_registry.get(int(pick_id))
    if not meta:
        return False
    return int(meta.get("roster_id") or 0) == int(roster_id)
