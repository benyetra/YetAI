"""Sleeper-first trade recommendations without Postgres league sync."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.fantasy_draft_picks import (
    calculate_faab_trade_value,
    format_roster_tradeable_picks,
    lookup_pick_trade_value,
)
from app.services.fantasy_sleeper_roster import (
    fetch_league_rosters,
    fetch_team_players_by_position,
    fetch_team_roster_players,
    find_roster_for_team,
)
from app.services.fantasy_sleeper_trade_proposal import load_league_pick_context
from app.services.fantasy_trade_value import select_trade_partner

POSITIONS = ("QB", "RB", "WR", "TE")
PICK_SURPLUS_POSITIONS = frozenset({"RB", "WR"})
EARLY_PICK_ROUNDS = frozenset({1, 2})

# Positions below these counts are considered roster needs.
STARTER_THRESHOLDS: Dict[str, int] = {
    "QB": 2,
    "RB": 3,
    "WR": 4,
    "TE": 2,
}

# Positions above these counts are considered tradeable surplus.
DEPTH_SURPLUS_THRESHOLDS: Dict[str, int] = {
    "QB": 2,
    "RB": 4,
    "WR": 6,
    "TE": 3,
}

MAX_VALUE_GAP_RATIO = 0.15
MIN_FAAB_REMAINING = 20
MAX_FAAB_OFFER = 25


def count_positions(roster: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count fantasy players by position on a roster."""
    counts: Dict[str, int] = {pos: 0 for pos in POSITIONS}
    for player in roster:
        pos = str(player.get("position") or "").upper()
        if pos in counts:
            counts[pos] += 1
    return counts


def identify_position_needs(counts: Dict[str, int]) -> List[str]:
    """Return positions where the roster is below starter depth."""
    return [pos for pos in POSITIONS if counts.get(pos, 0) < STARTER_THRESHOLDS[pos]]


def identify_position_surplus(counts: Dict[str, int]) -> List[str]:
    """Return positions where the roster exceeds comfortable depth."""
    return [
        pos for pos in POSITIONS if counts.get(pos, 0) > DEPTH_SURPLUS_THRESHOLDS[pos]
    ]


def partner_complement_score(
    user_needs: List[str],
    user_surplus: List[str],
    partner_counts: Dict[str, int],
) -> int:
    """
    Score how well a partner complements the user's roster profile.

    +1 when partner has surplus where the user has a need, and
    +1 when partner has a need where the user has surplus.
    """
    partner_needs = identify_position_needs(partner_counts)
    partner_surplus = identify_position_surplus(partner_counts)
    score = 0
    for pos in user_needs:
        if (
            pos in partner_surplus
            or partner_counts.get(pos, 0) > STARTER_THRESHOLDS[pos]
        ):
            score += 1
    for pos in user_surplus:
        if pos in partner_needs:
            score += 1
    return score


def select_complementary_partner(
    partner_teams: List[Dict[str, Any]],
    partner_rosters: Dict[int, List[Dict[str, Any]]],
    *,
    user_needs: List[str],
    user_surplus: List[str],
    seed: str,
) -> Optional[Dict[str, Any]]:
    """Pick a stable trade partner with the best complementary roster profile."""
    if not partner_teams:
        return None

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for team in partner_teams:
        team_id = team.get("team_id")
        if team_id is None:
            continue
        roster = partner_rosters.get(int(team_id), [])
        counts = count_positions(roster)
        score = partner_complement_score(user_needs, user_surplus, counts)
        if score > 0:
            scored.append((score, team))

    candidates = [team for _, team in scored]
    if not candidates:
        candidates = partner_teams

    return select_trade_partner(candidates, seed=seed)


def _players_at_position(
    roster: List[Dict[str, Any]],
    position: str,
    *,
    limit: int = 1,
    prefer_low_value: bool = False,
) -> List[Dict[str, Any]]:
    matches = [p for p in roster if p.get("position") == position]
    if not matches:
        return []
    matches.sort(
        key=lambda p: p.get("trade_value") or 0,
        reverse=not prefer_low_value,
    )
    return [_format_player(p) for p in matches[:limit]]


def _format_player(player: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": player.get("id") or player.get("player_id"),
        "name": player.get("name", "Unknown"),
        "position": player.get("position", "UNKNOWN"),
        "team": player.get("team", "UNKNOWN"),
        "age": player.get("age", 27),
        "trade_value": player.get("trade_value", 0),
    }


def _sum_trade_value(players: List[Dict[str, Any]]) -> float:
    return sum(float(p.get("trade_value") or 0) for p in players)


def _side_asset_value(
    players: List[Dict[str, Any]],
    *,
    pick_ids: Optional[List[int]] = None,
    pick_registry: Optional[Dict[int, Dict[str, Any]]] = None,
    faab: int = 0,
) -> float:
    total = _sum_trade_value(players)
    for pick_id in pick_ids or []:
        total += lookup_pick_trade_value(int(pick_id), pick_registry)
    total += calculate_faab_trade_value(int(faab or 0))
    return total


def value_gap_ratio(
    give_players: List[Dict[str, Any]], get_players: List[Dict[str, Any]]
) -> float:
    """Return absolute value gap as a fraction of the larger side (0..1)."""
    return _value_gap_ratio(give_players, get_players)


def _value_gap_ratio(
    give_players: List[Dict[str, Any]],
    get_players: List[Dict[str, Any]],
    *,
    give_picks: Optional[List[int]] = None,
    get_picks: Optional[List[int]] = None,
    give_faab: int = 0,
    get_faab: int = 0,
    pick_registry: Optional[Dict[int, Dict[str, Any]]] = None,
) -> float:
    """Return absolute value gap including picks and FAAB."""
    give_total = _side_asset_value(
        give_players,
        pick_ids=give_picks,
        pick_registry=pick_registry,
        faab=give_faab,
    )
    get_total = _side_asset_value(
        get_players,
        pick_ids=get_picks,
        pick_registry=pick_registry,
        faab=get_faab,
    )
    if give_total <= 0 and get_total <= 0:
        return 0.0
    larger = max(give_total, get_total)
    if larger <= 0:
        return 1.0
    return abs(give_total - get_total) / larger


def _priority_from_balance(base: int, gap_ratio: float) -> int:
    """Boost priority when trade value is balanced within ~15%."""
    if gap_ratio <= MAX_VALUE_GAP_RATIO:
        return min(100, base + 15)
    if gap_ratio <= 0.30:
        return base
    return max(20, base - 20)


def _confidence_from_balance(gap_ratio: float) -> int:
    if gap_ratio <= MAX_VALUE_GAP_RATIO:
        return 80
    if gap_ratio <= 0.30:
        return 70
    return 60


def _tradeable_give_candidates(
    roster: List[Dict[str, Any]],
    surplus_positions: List[str],
    *,
    exclude_positions: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    exclude = set(exclude_positions or [])
    candidates: List[Dict[str, Any]] = []
    for pos in surplus_positions:
        if pos in exclude:
            continue
        candidates.extend(
            _players_at_position(roster, pos, limit=2, prefer_low_value=True)
        )
    if candidates:
        return candidates[:2]

    for pos in POSITIONS:
        if pos in exclude:
            continue
        pos_players = _players_at_position(roster, pos, limit=3, prefer_low_value=True)
        if pos_players:
            candidates.extend(pos_players[:1])
            break
    return candidates[:2]


def _league_has_faab(league: Dict[str, Any]) -> bool:
    settings = league.get("settings") or {}
    waiver_budget = int(settings.get("waiver_budget") or 0)
    waiver_type = int(settings.get("waiver_type") or 0)
    return waiver_budget > 0 or waiver_type == 2


def _user_faab_remaining(
    league: Dict[str, Any], roster_doc: Optional[Dict[str, Any]]
) -> int:
    settings = league.get("settings") or {}
    budget = int(settings.get("waiver_budget") or 0)
    if budget <= 0:
        return 0
    roster_settings = (roster_doc or {}).get("settings") or {}
    used = int(roster_settings.get("waiver_budget_used") or 0)
    return max(0, budget - used)


def _early_round_picks(
    tradeable_picks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        pick
        for pick in tradeable_picks
        if int(pick.get("round") or 0) in EARLY_PICK_ROUNDS
    ]


def _select_pick_for_need(
    tradeable_picks: List[Dict[str, Any]],
    *,
    prefer_early: bool,
) -> Optional[Dict[str, Any]]:
    if not tradeable_picks:
        return None
    if prefer_early:
        early = _early_round_picks(tradeable_picks)
        if early:
            return early[0]
    return tradeable_picks[0]


def build_pick_trade_recommendation(
    *,
    need_position: str,
    user_roster: List[Dict[str, Any]],
    user_surplus: List[str],
    tradeable_picks: List[Dict[str, Any]],
    partner_roster: List[Dict[str, Any]],
    partner_id: int,
    partner_name: str,
    pick_registry: Dict[int, Dict[str, Any]],
    is_dynasty: bool,
) -> Optional[Dict[str, Any]]:
    """Build a pick-inclusive trade when dynasty or the user holds extra picks."""
    if not (is_dynasty or len(tradeable_picks) >= 2):
        return None

    partner_counts = count_positions(partner_roster)
    partner_surplus = identify_position_surplus(partner_counts)
    has_pick_surplus = any(pos in PICK_SURPLUS_POSITIONS for pos in user_surplus)
    early_picks = _early_round_picks(tradeable_picks)
    many_picks = len(tradeable_picks) >= 3

    prefer_early = bool(has_pick_surplus and early_picks)
    if not many_picks and not prefer_early:
        return None
    if (
        need_position not in partner_surplus
        and partner_counts.get(need_position, 0) <= STARTER_THRESHOLDS[need_position]
    ):
        return None

    we_get = _players_at_position(partner_roster, need_position, limit=1)
    if not we_get:
        return None

    pick = _select_pick_for_need(tradeable_picks, prefer_early=prefer_early)
    if not pick:
        return None

    surplus_positions = [
        pos for pos in user_surplus if pos in PICK_SURPLUS_POSITIONS
    ] or user_surplus
    we_give_players = _tradeable_give_candidates(
        user_roster,
        surplus_positions,
        exclude_positions=[need_position],
    )
    if not we_give_players and many_picks:
        we_give_players = _tradeable_give_candidates(
            user_roster,
            user_surplus,
            exclude_positions=[need_position],
        )
    if not we_give_players:
        return None

    pick_id = int(pick["pick_id"])
    pick_desc = pick.get("description") or f"Round {pick.get('round')} pick"
    gap = _value_gap_ratio(
        we_give_players,
        we_get,
        give_picks=[pick_id],
        pick_registry=pick_registry,
    )
    base_priority = 72 if is_dynasty else 68

    return {
        "recommendation_type": f"{need_position} Pick Upgrade",
        "type": "pick_trade",
        "title": f"Trade Pick for {need_position} Upgrade",
        "description": (
            f"Package {pick_desc} with depth to acquire {need_position} "
            f"help from {partner_name}."
        ),
        "target_team_id": partner_id,
        "we_give": {
            "players": we_give_players[:1],
            "picks": [pick_id],
            "faab": 0,
        },
        "we_get": {"players": we_get, "picks": [], "faab": 0},
        "priority_score": _priority_from_balance(base_priority, gap),
        "confidence": _confidence_from_balance(gap),
        "reasoning": (
            f"You hold {pick_desc} and surplus depth; {partner_name} has "
            f"{need_position} to spare for a win-now upgrade."
        ),
        "trade_partner": partner_name,
    }


def build_faab_trade_recommendation(
    *,
    need_position: str,
    user_roster: List[Dict[str, Any]],
    user_surplus: List[str],
    faab_remaining: int,
    partner_roster: List[Dict[str, Any]],
    partner_id: int,
    partner_name: str,
) -> Optional[Dict[str, Any]]:
    """Suggest FAAB plus a bench player for a starter at a need position."""
    if faab_remaining <= MIN_FAAB_REMAINING:
        return None

    we_get = _players_at_position(partner_roster, need_position, limit=1)
    if not we_get:
        return None

    we_give_players = _tradeable_give_candidates(
        user_roster,
        user_surplus,
        exclude_positions=[need_position],
    )
    if not we_give_players:
        we_give_players = _tradeable_give_candidates(
            user_roster,
            list(POSITIONS),
            exclude_positions=[need_position],
        )
    if not we_give_players:
        return None

    faab_offer = min(MAX_FAAB_OFFER, max(1, faab_remaining // 4))
    gap = _value_gap_ratio(
        we_give_players[:1],
        we_get,
        give_faab=faab_offer,
    )
    base_priority = 58

    return {
        "recommendation_type": f"{need_position} FAAB Upgrade",
        "type": "faab_trade",
        "title": f"Add {need_position} with FAAB",
        "description": (
            f"Offer ${faab_offer} FAAB plus depth to {partner_name} "
            f"for a {need_position} upgrade."
        ),
        "target_team_id": partner_id,
        "we_give": {
            "players": we_give_players[:1],
            "picks": [],
            "faab": faab_offer,
        },
        "we_get": {"players": we_get, "picks": [], "faab": 0},
        "priority_score": _priority_from_balance(base_priority, gap),
        "confidence": _confidence_from_balance(gap),
        "reasoning": (
            f"With ${faab_remaining} FAAB left, pairing ${faab_offer} with "
            f"a expendable piece can land {need_position} help from "
            f"{partner_name}."
        ),
        "trade_partner": partner_name,
    }


def _recommendation_templates(
    needs: List[str],
    surplus: List[str],
) -> List[Dict[str, Any]]:
    """Build need/surplus-driven recommendation specs."""
    templates: List[Dict[str, Any]] = []
    for pos in needs:
        templates.append(
            {
                "kind": "need",
                "position": pos,
                "recommendation_type": f"{pos} Depth Needed",
                "type": "depth_addition",
                "title": f"Add {pos} Depth",
                "base_priority": 60 if pos in {"QB", "RB"} else 55,
            }
        )
    for pos in surplus:
        templates.append(
            {
                "kind": "surplus",
                "position": pos,
                "recommendation_type": f"{pos} Surplus Trade",
                "type": "position_balance",
                "title": f"Trade Excess {pos} Depth",
                "base_priority": 70 if pos == "RB" else 65,
            }
        )
    return templates


async def generate_sleeper_trade_recommendations(
    *,
    sleeper_service,
    league_id: str,
    team_id: int,
    scoring_type: str,
    league_format: Optional[Dict[str, Any]] = None,
    max_recommendations: int = 10,
) -> List[Dict[str, Any]]:
    """Generate Sleeper-only trade recommendations for one team."""
    pick_ctx = await load_league_pick_context(sleeper_service, league_id)
    league = pick_ctx["league"]
    pick_registry = pick_ctx["pick_registry"]
    is_dynasty = bool(pick_ctx.get("is_dynasty"))
    if league_format is None:
        league_format = pick_ctx.get("league_format")

    tradeable_picks = format_roster_tradeable_picks(
        league,
        pick_ctx.get("traded_picks") or [],
        int(team_id),
    )

    raw_rosters = await fetch_league_rosters(league_id)
    user_roster_doc = find_roster_for_team(raw_rosters, int(team_id))
    faab_remaining = (
        _user_faab_remaining(league, user_roster_doc) if _league_has_faab(league) else 0
    )

    user_roster = await fetch_team_roster_players(
        sleeper_service,
        league_id,
        int(team_id),
        scoring_type=scoring_type,
        league_format=league_format,
    )
    if not user_roster:
        return []

    league_teams = await sleeper_service.get_league_teams(str(league_id))
    other_teams = [
        team for team in league_teams if str(team.get("team_id")) != str(team_id)
    ]

    partner_rosters: Dict[int, List[Dict[str, Any]]] = {}
    for team in other_teams:
        partner_id = team.get("team_id")
        if partner_id is None:
            continue
        partner_rosters[int(partner_id)] = await fetch_team_roster_players(
            sleeper_service,
            league_id,
            int(partner_id),
            scoring_type=scoring_type,
            league_format=league_format,
        )

    user_counts = count_positions(user_roster)
    user_needs = identify_position_needs(user_counts)
    user_surplus = identify_position_surplus(user_counts)

    recommendations: List[Dict[str, Any]] = []
    rec_id = 1
    seen_keys: set[str] = set()

    def _append_rec(rec: Dict[str, Any]) -> None:
        nonlocal rec_id
        key = (
            f"{rec.get('type')}:{rec.get('target_team_id')}:"
            f"{rec.get('recommendation_type')}"
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        rec["id"] = rec_id
        rec["estimated_likelihood"] = round(rec["confidence"] / 100, 2)
        recommendations.append(rec)
        rec_id += 1

    for template in _recommendation_templates(user_needs, user_surplus):
        pos = template["position"]
        seed = f"{team_id}:{template['kind']}:{pos}"
        partner = select_complementary_partner(
            other_teams,
            partner_rosters,
            user_needs=user_needs,
            user_surplus=user_surplus,
            seed=seed,
        )
        if not partner:
            continue

        partner_id = partner.get("team_id")
        partner_name = partner.get("name", f"Team {partner_id}")
        partner_roster = partner_rosters.get(int(partner_id), [])

        if template["kind"] == "need":
            we_get = _players_at_position(partner_roster, pos, limit=1)
            if not we_get:
                we_get = await fetch_team_players_by_position(
                    sleeper_service,
                    league_id,
                    int(partner_id),
                    pos,
                    limit=1,
                    scoring_type=scoring_type,
                    league_format=league_format,
                )
                we_get = [_format_player(p) for p in we_get]
            if not we_get:
                continue

            we_give = _tradeable_give_candidates(
                user_roster,
                user_surplus,
                exclude_positions=[pos],
            )
            description = (
                f"Consider trading for {pos} depth from {partner_name} "
                f"to address a roster need."
            )
            reasoning = (
                f"Limited {pos} depth could hurt lineup flexibility. "
                f"{partner_name} may have {pos} depth to spare."
            )
        else:
            we_give = _players_at_position(
                user_roster, pos, limit=2, prefer_low_value=True
            )
            if not we_give:
                continue

            partner_counts = count_positions(partner_roster)
            partner_needs = identify_position_needs(partner_counts)
            target_positions = [p for p in partner_needs if p != pos] or [
                p for p in POSITIONS if p != pos
            ][:2]

            we_get = []
            for target_pos in target_positions:
                we_get.extend(_players_at_position(partner_roster, target_pos, limit=1))
                if we_get:
                    break
            if not we_get and target_positions:
                fetched = await fetch_team_players_by_position(
                    sleeper_service,
                    league_id,
                    int(partner_id),
                    target_positions[0],
                    limit=1,
                    scoring_type=scoring_type,
                    league_format=league_format,
                )
                we_get = [_format_player(p) for p in fetched]
            if not we_get:
                continue

            description = (
                f"Trade surplus {pos} depth to {partner_name} "
                f"for positional upgrades."
            )
            reasoning = (
                f"With {user_counts.get(pos, 0)} {pos}s, you can move depth "
                f"for upgrades. {partner_name} may need {pos} help."
            )

        gap = _value_gap_ratio(we_give, we_get)
        _append_rec(
            {
                "recommendation_type": template["recommendation_type"],
                "type": template["type"],
                "title": template["title"],
                "description": description,
                "target_team_id": partner_id,
                "we_give": {"players": we_give, "picks": [], "faab": 0},
                "we_get": {"players": we_get, "picks": [], "faab": 0},
                "confidence": _confidence_from_balance(gap),
                "priority_score": _priority_from_balance(
                    template["base_priority"], gap
                ),
                "reasoning": reasoning,
                "trade_partner": partner_name,
            }
        )

    pick_eligible = is_dynasty or len(tradeable_picks) >= 2
    if pick_eligible and user_needs:
        for pos in user_needs:
            seed = f"{team_id}:pick:{pos}"
            partner = select_complementary_partner(
                other_teams,
                partner_rosters,
                user_needs=user_needs,
                user_surplus=user_surplus,
                seed=seed,
            )
            if not partner:
                continue
            partner_id = int(partner["team_id"])
            partner_name = partner.get("name", f"Team {partner_id}")
            pick_rec = build_pick_trade_recommendation(
                need_position=pos,
                user_roster=user_roster,
                user_surplus=user_surplus,
                tradeable_picks=tradeable_picks,
                partner_roster=partner_rosters.get(partner_id, []),
                partner_id=partner_id,
                partner_name=partner_name,
                pick_registry=pick_registry,
                is_dynasty=is_dynasty,
            )
            if pick_rec:
                _append_rec(pick_rec)

    if faab_remaining > MIN_FAAB_REMAINING and user_needs:
        for pos in user_needs:
            seed = f"{team_id}:faab:{pos}"
            partner = select_complementary_partner(
                other_teams,
                partner_rosters,
                user_needs=user_needs,
                user_surplus=user_surplus,
                seed=seed,
            )
            if not partner:
                continue
            partner_id = int(partner["team_id"])
            partner_name = partner.get("name", f"Team {partner_id}")
            faab_rec = build_faab_trade_recommendation(
                need_position=pos,
                user_roster=user_roster,
                user_surplus=user_surplus,
                faab_remaining=faab_remaining,
                partner_roster=partner_rosters.get(partner_id, []),
                partner_id=partner_id,
                partner_name=partner_name,
            )
            if faab_rec:
                _append_rec(faab_rec)

    recommendations.sort(key=lambda rec: rec["priority_score"], reverse=True)
    return recommendations[:max_recommendations]
