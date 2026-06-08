"""Sleeper-only trade validation, evaluation, and proposal (no DB sync required)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.fantasy_draft_picks import (
    build_league_pick_registry,
    calculate_faab_trade_value,
    lookup_pick_trade_value,
    pick_owned_by_roster,
)
from app.services.fantasy_league_format import league_format_from_sleeper
from app.services.fantasy_player_compare import scoring_type_from_sleeper_league
from app.services.fantasy_sleeper_roster import (
    fetch_league_rosters,
    find_roster_for_team,
)
from app.services.fantasy_trade_value import (
    calculate_deterministic_trade_value,
    stable_unit,
)

logger = logging.getLogger(__name__)


async def load_league_pick_context(
    sleeper_service: Any, league_id: str
) -> Dict[str, Any]:
    """Fetch league metadata, traded picks, and pick registry."""
    league = await sleeper_service.get_league(league_id)
    traded_picks = await sleeper_service.get_league_traded_picks(league_id)
    registry = build_league_pick_registry(league, traded_picks)
    return {
        "league": league,
        "traded_picks": traded_picks,
        "pick_registry": registry,
        "is_dynasty": int((league.get("settings") or {}).get("type", 0)) == 2,
        "league_format": league_format_from_sleeper(league),
    }


def calculate_realistic_trade_value(
    player: Dict[str, Any],
    *,
    scoring_type: str = "ppr",
    league_format: Optional[Dict[str, Any]] = None,
) -> float:
    return calculate_deterministic_trade_value(
        player,
        scoring_type=scoring_type,
        league_format=league_format,
    )


def _side_gives_something(assets: Dict[str, Any]) -> bool:
    return bool(
        assets.get("players") or assets.get("picks") or int(assets.get("faab") or 0) > 0
    )


async def _roster_player_ids(platform_league_id: str, roster_id: int) -> set[str]:
    rosters = await fetch_league_rosters(platform_league_id)
    roster = find_roster_for_team(rosters, roster_id)
    if not roster:
        return set()
    return {str(player_id) for player_id in (roster.get("players") or []) if player_id}


def _validate_team_gives(
    *,
    roster_id: int,
    assets: Dict[str, Any],
    roster_player_ids: set[str],
    pick_registry: Dict[int, Dict[str, Any]],
    team_label: str,
) -> Optional[str]:
    if not _side_gives_something(assets):
        return f"{team_label} must give something"

    for player_id in assets.get("players") or []:
        if str(player_id) not in roster_player_ids:
            return f"{team_label} doesn't own player {player_id}"

    for pick_id in assets.get("picks") or []:
        if not pick_owned_by_roster(int(pick_id), roster_id, pick_registry):
            return f"{team_label} doesn't own pick {pick_id}"

    faab = int(assets.get("faab") or 0)
    if faab < 0:
        return f"{team_label} FAAB must be non-negative"

    return None


async def validate_sleeper_trade_assets(
    *,
    sleeper_service: Any,
    platform_league_id: str,
    team1_roster_id: int,
    team2_roster_id: int,
    team1_gives: dict,
    team2_gives: dict,
    pick_registry: dict,
) -> dict:
    """Validate Sleeper roster ownership and that both sides offer assets."""
    del sleeper_service  # reserved for future Sleeper API fallbacks

    team1_players = await _roster_player_ids(platform_league_id, team1_roster_id)
    team2_players = await _roster_player_ids(platform_league_id, team2_roster_id)

    if not team1_players and (team1_gives.get("players") or []):
        return {"valid": False, "error": "Team 1 roster not found"}
    if not team2_players and (team2_gives.get("players") or []):
        return {"valid": False, "error": "Team 2 roster not found"}

    team1_error = _validate_team_gives(
        roster_id=team1_roster_id,
        assets=team1_gives,
        roster_player_ids=team1_players,
        pick_registry=pick_registry,
        team_label="Team 1",
    )
    if team1_error:
        return {"valid": False, "error": team1_error}

    team2_error = _validate_team_gives(
        roster_id=team2_roster_id,
        assets=team2_gives,
        roster_player_ids=team2_players,
        pick_registry=pick_registry,
        team_label="Team 2",
    )
    if team2_error:
        return {"valid": False, "error": team2_error}

    return {"valid": True}


def _analyze_trade_side(
    assets: Dict[str, Any],
    *,
    all_players: Dict[str, Any],
    pick_registry: Dict[int, Dict[str, Any]],
    scoring_type: str,
    league_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    total_value = 0.0
    side_analysis: Dict[str, Any] = {
        "players": [],
        "picks": [],
        "faab": assets.get("faab", 0) or 0,
        "total_value": 0,
        "positions": {},
        "avg_age": 0,
    }

    ages: List[float] = []
    for player_id in assets.get("players") or []:
        if str(player_id) not in all_players:
            continue
        player_data = all_players[str(player_id)]
        name = (
            f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}"
        ).strip()
        position = player_data.get("position", "UNKNOWN")
        age = player_data.get("age", 27)
        trade_value = calculate_realistic_trade_value(
            player_data,
            scoring_type=scoring_type,
            league_format=league_format,
        )

        player_info = {
            "player_id": player_id,
            "name": name,
            "position": position,
            "team": player_data.get("team", "FA"),
            "age": age,
            "trade_value": round(trade_value, 1),
        }

        side_analysis["players"].append(player_info)
        total_value += trade_value
        ages.append(float(age))
        side_analysis["positions"][position] = (
            side_analysis["positions"].get(position, 0) + 1
        )

    for pick_id in assets.get("picks") or []:
        pick_value = lookup_pick_trade_value(int(pick_id), pick_registry)
        meta = pick_registry.get(int(pick_id), {})
        pick_info = {
            "pick_id": int(pick_id),
            "description": meta.get("description", f"Pick {pick_id}"),
            "season": meta.get("season"),
            "round": meta.get("round"),
            "trade_value": round(pick_value, 1),
        }
        side_analysis["picks"].append(pick_info)
        total_value += pick_value

    faab_amount = int(assets.get("faab") or 0)
    if faab_amount > 0:
        faab_value = calculate_faab_trade_value(faab_amount)
        side_analysis["faab_value"] = round(faab_value, 1)
        total_value += faab_value

    side_analysis["total_value"] = round(total_value, 1)
    side_analysis["avg_age"] = round(sum(ages) / len(ages) if ages else 0, 1)

    return side_analysis


def _format_insight(insight_text: str) -> Dict[str, str]:
    impact = "medium"
    category = "general"

    if "more value" in insight_text or "compensation" in insight_text:
        impact = "high"
        category = "value_analysis"
    elif "older players" in insight_text or "young talent" in insight_text:
        impact = "medium"
        category = "age_analysis"
    elif "QB" in insight_text:
        impact = "high"
        category = "position_strategy"
    elif "elite player" in insight_text or "star-for-star" in insight_text:
        impact = "high"
        category = "player_value"
    elif "consolidation" in insight_text or "multiple players" in insight_text:
        impact = "medium"
        category = "roster_construction"
    elif "well-matched" in insight_text or "good trade balance" in insight_text:
        impact = "low"
        category = "trade_balance"
    elif "swap" in insight_text or "strategies" in insight_text:
        impact = "medium"
        category = "position_strategy"

    return {"category": category, "description": insight_text, "impact": impact}


def _generate_trade_insights(
    team1_gives: Dict[str, Any], team2_gives: Dict[str, Any], fairness_pct: float
) -> List[Dict[str, str]]:
    insights: List[str] = []
    value_diff = abs(team1_gives["total_value"] - team2_gives["total_value"])

    if team1_gives.get("picks") or team2_gives.get("picks"):
        insights.append(
            "Draft picks included — future value affects dynasty/redraft balance"
        )
    if (team1_gives.get("faab") or 0) > 0 or (team2_gives.get("faab") or 0) > 0:
        insights.append(
            "FAAB included — budget value discounted vs in-season waiver spend"
        )

    if team1_gives["avg_age"] > team2_gives["avg_age"] + 3:
        insights.append(
            f"Team 1 trading older players (avg age {team1_gives['avg_age']:.1f} vs {team2_gives['avg_age']:.1f})"
        )
    elif team2_gives["avg_age"] > team1_gives["avg_age"] + 3:
        insights.append(
            f"Team 2 trading older players (avg age {team2_gives['avg_age']:.1f} vs {team1_gives['avg_age']:.1f})"
        )

    if value_diff > 10:
        if team1_gives["total_value"] > team2_gives["total_value"]:
            insights.append(
                f"Team 1 giving up {value_diff:.1f} more value - may need compensation"
            )
        else:
            insights.append(
                f"Team 2 giving up {value_diff:.1f} more value - may need compensation"
            )

    if len(team1_gives["players"]) > len(team2_gives["players"]) + 1:
        insights.append(
            "Team 1 trading multiple players for fewer elite players (talent consolidation)"
        )
    elif len(team2_gives["players"]) > len(team1_gives["players"]) + 1:
        insights.append(
            "Team 2 trading multiple players for fewer elite players (talent consolidation)"
        )

    team1_positions = list(team1_gives["positions"].keys())
    team2_positions = list(team2_gives["positions"].keys())

    if "QB" in team1_positions or "QB" in team2_positions:
        insights.append("QB involved - high-impact position trade")

    if "RB" in team1_positions and "WR" in team2_positions:
        insights.append("RB for WR swap - different positional strategies")
    elif "WR" in team1_positions and "RB" in team2_positions:
        insights.append("WR for RB swap - different positional strategies")

    team1_high_value = [p for p in team1_gives["players"] if p["trade_value"] > 25]
    team2_high_value = [p for p in team2_gives["players"] if p["trade_value"] > 25]

    if team1_high_value and not team2_high_value:
        insights.append(
            f"Team 1 trading elite player ({team1_high_value[0]['name']}) for depth"
        )
    elif team2_high_value and not team1_high_value:
        insights.append(
            f"Team 2 trading elite player ({team2_high_value[0]['name']}) for depth"
        )
    elif team1_high_value and team2_high_value:
        insights.append("Elite players on both sides - star-for-star trade")

    team1_young = [p for p in team1_gives["players"] if p["age"] <= 24]
    team2_young = [p for p in team2_gives["players"] if p["age"] <= 24]

    if team1_young and not team2_young:
        insights.append("Team 1 trading young talent for immediate production")
    elif team2_young and not team1_young:
        insights.append("Team 2 trading young talent for immediate production")

    if not insights:
        if fairness_pct >= 85:
            insights.append("Values are well-matched - good trade balance")
        elif team1_gives["total_value"] > team2_gives["total_value"]:
            insights.append(
                "Team 1 giving up more value - consider additional compensation"
            )
        else:
            insights.append(
                "Team 2 giving up more value - consider additional compensation"
            )

    return [_format_insight(text) for text in insights]


def _fairness_verdict(fairness_pct: float) -> tuple[str, str]:
    if fairness_pct >= 90:
        return "Fair Trade", "green"
    if fairness_pct >= 75:
        return "Slightly Uneven", "yellow"
    if fairness_pct >= 60:
        return "Uneven Trade", "orange"
    return "Very Uneven", "red"


def build_sleeper_trade_evaluation(
    *,
    platform_league_id: str,
    team1_roster_id: int,
    team2_roster_id: int,
    team1_gives_raw: Dict[str, Any],
    team2_gives_raw: Dict[str, Any],
    all_players: Dict[str, Any],
    pick_registry: Dict[int, Dict[str, Any]],
    scoring_type: str,
    league_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build quick-analysis evaluation payload from Sleeper trade assets."""
    team1_gives = _analyze_trade_side(
        team1_gives_raw,
        all_players=all_players,
        pick_registry=pick_registry,
        scoring_type=scoring_type,
        league_format=league_format,
    )
    team2_gives = _analyze_trade_side(
        team2_gives_raw,
        all_players=all_players,
        pick_registry=pick_registry,
        scoring_type=scoring_type,
        league_format=league_format,
    )

    value_diff = abs(team1_gives["total_value"] - team2_gives["total_value"])
    total_value = team1_gives["total_value"] + team2_gives["total_value"]
    fairness_pct = (
        max(0, 100 - (value_diff / total_value * 100)) if total_value > 0 else 0
    )
    verdict, verdict_color = _fairness_verdict(fairness_pct)
    structured_insights = _generate_trade_insights(
        team1_gives, team2_gives, fairness_pct
    )

    trade_seed = (
        f"{platform_league_id}:{team1_roster_id}:{team2_roster_id}:"
        f"{team1_gives_raw}:{team2_gives_raw}"
    )
    trade_suffix = int(stable_unit(trade_seed) * 1_000_000_000)

    return {
        "trade_id": f"{team1_roster_id}_{team2_roster_id}_{trade_suffix}",
        "team1_gives": team1_gives,
        "team2_gives": team2_gives,
        "fairness": {
            "percentage": round(fairness_pct, 1),
            "verdict": verdict,
            "verdict_color": verdict_color,
            "value_difference": round(value_diff, 1),
        },
        "insights": structured_insights,
        "recommendation": verdict,
    }


async def evaluate_sleeper_trade(
    *,
    sleeper_service: Any,
    platform_league_id: str,
    team1_roster_id: int,
    team2_roster_id: int,
    team1_gives: dict,
    team2_gives: dict,
    pick_registry: Optional[dict] = None,
    scoring_type: Optional[str] = None,
    league_format: Optional[Dict[str, Any]] = None,
) -> dict:
    """Evaluate a Sleeper trade using the same shape as quick-analysis."""
    if pick_registry is None or scoring_type is None or league_format is None:
        pick_ctx = await load_league_pick_context(sleeper_service, platform_league_id)
        pick_registry = pick_registry or pick_ctx["pick_registry"]
        scoring_type = scoring_type or scoring_type_from_sleeper_league(
            pick_ctx["league"]
        )
        league_format = league_format or pick_ctx["league_format"]

    all_players = await sleeper_service._get_all_players()

    return build_sleeper_trade_evaluation(
        platform_league_id=platform_league_id,
        team1_roster_id=team1_roster_id,
        team2_roster_id=team2_roster_id,
        team1_gives_raw=team1_gives,
        team2_gives_raw=team2_gives,
        all_players=all_players,
        pick_registry=pick_registry,
        scoring_type=scoring_type,
        league_format=league_format,
    )


async def _try_persist_trade(
    db: Session,
    *,
    platform_league_id: str,
    team1_roster_id: int,
    team2_roster_id: int,
    team1_gives: dict,
    team2_gives: dict,
    trade_reason: Optional[str],
) -> Optional[Dict[str, Any]]:
    from app.models.fantasy_models import FantasyLeague, FantasyPlatform, FantasyTeam
    from app.services.trade_analyzer_service import TradeAnalyzerService

    league = (
        db.query(FantasyLeague)
        .filter(
            FantasyLeague.platform == FantasyPlatform.SLEEPER,
            FantasyLeague.platform_league_id == str(platform_league_id),
        )
        .first()
    )
    if not league:
        return None

    team1 = (
        db.query(FantasyTeam)
        .filter(
            FantasyTeam.league_id == league.id,
            FantasyTeam.platform_team_id == str(team1_roster_id),
        )
        .first()
    )
    team2 = (
        db.query(FantasyTeam)
        .filter(
            FantasyTeam.league_id == league.id,
            FantasyTeam.platform_team_id == str(team2_roster_id),
        )
        .first()
    )
    if not team1 or not team2:
        return None

    service = TradeAnalyzerService(db)
    return service.propose_trade(
        league_id=league.id,
        proposing_team_id=team1.id,
        target_team_id=team2.id,
        team1_gives=team1_gives,
        team2_gives=team2_gives,
        trade_reason=trade_reason,
    )


async def propose_sleeper_trade(
    *,
    sleeper_service: Any,
    platform_league_id: str,
    team1_roster_id: int,
    team2_roster_id: int,
    team1_gives: dict,
    team2_gives: dict,
    pick_registry: Optional[dict] = None,
    scoring_type: Optional[str] = None,
    league_format: Optional[Dict[str, Any]] = None,
    trade_reason: Optional[str] = None,
    persist: bool = False,
    db: Optional[Session] = None,
) -> dict:
    """Validate, evaluate, and optionally persist a Sleeper trade proposal."""
    pick_ctx = await load_league_pick_context(sleeper_service, platform_league_id)
    pick_registry = pick_registry or pick_ctx["pick_registry"]
    scoring_type = scoring_type or scoring_type_from_sleeper_league(pick_ctx["league"])
    league_format = league_format or pick_ctx["league_format"]

    validation = await validate_sleeper_trade_assets(
        sleeper_service=sleeper_service,
        platform_league_id=platform_league_id,
        team1_roster_id=team1_roster_id,
        team2_roster_id=team2_roster_id,
        team1_gives=team1_gives,
        team2_gives=team2_gives,
        pick_registry=pick_registry,
    )
    if not validation.get("valid"):
        return {"success": False, "error": validation.get("error", "Invalid trade")}

    evaluation = await evaluate_sleeper_trade(
        sleeper_service=sleeper_service,
        platform_league_id=platform_league_id,
        team1_roster_id=team1_roster_id,
        team2_roster_id=team2_roster_id,
        team1_gives=team1_gives,
        team2_gives=team2_gives,
        pick_registry=pick_registry,
        scoring_type=scoring_type,
        league_format=league_format,
    )

    response: Dict[str, Any] = {
        "success": True,
        "validated": True,
        "evaluation": evaluation,
        "persisted": False,
    }

    if persist and db is not None:
        persist_result = await _try_persist_trade(
            db,
            platform_league_id=platform_league_id,
            team1_roster_id=team1_roster_id,
            team2_roster_id=team2_roster_id,
            team1_gives=team1_gives,
            team2_gives=team2_gives,
            trade_reason=trade_reason,
        )
        if persist_result and persist_result.get("success"):
            response["persisted"] = True
            response["trade_id"] = persist_result.get("trade_id")
            if persist_result.get("evaluation"):
                response["db_evaluation"] = persist_result["evaluation"]

    return response
