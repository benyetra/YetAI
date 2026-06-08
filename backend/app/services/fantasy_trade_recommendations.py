"""Sleeper-first trade recommendations without Postgres league sync."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.fantasy_sleeper_roster import (
    fetch_team_players_by_position,
    fetch_team_roster_players,
)
from app.services.fantasy_trade_value import select_trade_partner

POSITIONS = ("QB", "RB", "WR", "TE")

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


def value_gap_ratio(
    give_players: List[Dict[str, Any]], get_players: List[Dict[str, Any]]
) -> float:
    """Return absolute value gap as a fraction of the larger side (0..1)."""
    give_total = _sum_trade_value(give_players)
    get_total = _sum_trade_value(get_players)
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

            give_positions = user_surplus or [p for p in POSITIONS if p != pos]
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

            we_get: List[Dict[str, Any]] = []
            for target_pos in target_positions:
                we_get.extend(_players_at_position(partner_roster, target_pos, limit=1))
                if we_get:
                    break
            if not we_get and target_positions:
                we_get = await fetch_team_players_by_position(
                    sleeper_service,
                    league_id,
                    int(partner_id),
                    target_positions[0],
                    limit=1,
                    scoring_type=scoring_type,
                    league_format=league_format,
                )
                we_get = [_format_player(p) for p in we_get]
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

        gap = value_gap_ratio(we_give, we_get)
        priority_score = _priority_from_balance(template["base_priority"], gap)
        confidence = _confidence_from_balance(gap)

        recommendations.append(
            {
                "id": rec_id,
                "recommendation_type": template["recommendation_type"],
                "type": template["type"],
                "title": template["title"],
                "description": description,
                "target_team_id": partner_id,
                "we_give": {"players": we_give, "picks": []},
                "we_get": {"players": we_get, "picks": []},
                "confidence": confidence,
                "estimated_likelihood": round(confidence / 100, 2),
                "priority_score": priority_score,
                "reasoning": reasoning,
                "trade_partner": partner_name,
            }
        )
        rec_id += 1

    recommendations.sort(key=lambda rec: rec["priority_score"], reverse=True)
    return recommendations[:max_recommendations]
