"""
Fantasy API routes (extracted from main.py — ojg.9).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])

from app.api.fantasy.trade_value import (
    calculate_faab_trade_value,
    calculate_realistic_trade_value,
    load_league_pick_context,
    lookup_pick_trade_value,
    format_roster_traded_picks,
)
from app.services.fantasy_player_compare import scoring_type_from_sleeper_league
from app.services.fantasy_trade_value import stable_unit
from app.services.fantasy_sleeper_roster import fetch_team_roster_players
from app.services.fantasy_trade_recommendations import (
    generate_sleeper_trade_recommendations,
)


# Trade Analyzer Endpoints
@router.get("/api/v1/fantasy/trade-analyzer/team-analysis/{team_id}")
async def get_simple_team_analysis(
    team_id: int, league_id: int = None, current_user: dict = Depends(get_current_user)
):
    """Get team analysis - REAL DATA ONLY, fetched directly from Sleeper API"""
    logger.info(
        f"🔍 TEAM ANALYSIS CALLED - Team: {team_id}, League: {league_id}, User: {current_user['user_id']}"
    )

    if not league_id:
        raise HTTPException(status_code=400, detail="league_id parameter is required")

    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        league_doc = await sleeper_service.get_league(str(league_id))
        scoring_type = scoring_type_from_sleeper_league(league_doc)

        # Get teams and standings data from Sleeper API
        logger.info(f"🔍 GETTING LEAGUE DATA from Sleeper API for league {league_id}")
        teams = await sleeper_service.get_league_teams(str(league_id))

        # Get standings data directly from SleeperFantasyService
        logger.info(
            f"🔍 GETTING STANDINGS DATA from Sleeper API for league {league_id}"
        )
        try:
            standings_data = await sleeper_service.get_league_standings(str(league_id))
            logger.info(f"🔍 FOUND {len(standings_data)} teams in standings")
        except Exception as e:
            logger.warning(f"Error fetching standings: {e}")
            standings_data = []

        # Find the specific team by team_id from both teams and standings
        team_data = None
        standings_team_data = None

        # Find team in teams data
        for team in teams:
            if team.get("team_id") == team_id or str(team.get("team_id")) == str(
                team_id
            ):
                team_data = team
                break

        # Find team in standings data
        for team in standings_data:
            if (
                team.get("team_id") == str(team_id)
                or int(team.get("team_id", 0)) == team_id
            ):
                standings_team_data = team
                break

        if not team_data:
            logger.warning(
                f"Team {team_id} not found in teams data, using first available team"
            )
            team_data = teams[0] if teams else {}

        if not standings_team_data:
            logger.warning(f"Team {team_id} not found in standings data")
            standings_team_data = {}

        # Get roster data for this team from Sleeper API
        logger.info("🔍 GETTING ROSTER DATA from Sleeper API")
        roster_data = await fetch_team_roster_players(
            sleeper_service,
            str(league_id),
            int(team_id),
            scoring_type=scoring_type,
        )
        logger.info("🔍 FOUND %s players for team %s", len(roster_data), team_id)

        tradeable_picks: list = []
        try:
            pick_ctx = await load_league_pick_context(sleeper_service, str(league_id))
            tradeable_picks = format_roster_traded_picks(
                pick_ctx["league"], pick_ctx["traded_picks"], int(team_id)
            )
            logger.info(
                "Found %s tradeable picks for roster %s",
                len(tradeable_picks),
                team_id,
            )
        except Exception as pick_error:
            logger.warning("Could not load tradeable picks: %s", pick_error)

        # Build comprehensive team analysis response
        logger.info(
            f"🔍 TEAM ANALYSIS COMPLETE: {len(roster_data)} players for team {team_data.get('name', f'Team {team_id}')}"
        )

        # Calculate position analysis
        position_counts = {}
        position_strengths = {}
        position_needs = {}

        for player in roster_data:
            pos = player["position"]
            position_counts[pos] = position_counts.get(pos, 0) + 1

        # Calculate strengths and needs based on roster composition
        for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            count = position_counts.get(pos, 0)
            position_strengths[pos] = count * 20  # Strength based on player count

            # Determine need level (higher = more need)
            if pos == "QB":
                position_needs[pos] = 3 if count < 2 else 1
            elif pos in ["RB", "WR"]:
                position_needs[pos] = 3 if count < 3 else 1
            elif pos == "TE":
                position_needs[pos] = 3 if count < 2 else 1
            else:
                position_needs[pos] = 3 if count < 1 else 1

        # Identify surplus positions
        surplus_positions = []
        for pos, count in position_counts.items():
            if (
                (pos == "WR" and count > 4)
                or (pos == "RB" and count > 3)
                or (pos in ["QB", "TE"] and count > 2)
            ):
                surplus_positions.append(pos)

        # Sort players by trade value (highest to lowest)
        sorted_players = sorted(
            roster_data, key=lambda p: p.get("trade_value", 0), reverse=True
        )

        # Create tradeable assets lists based on actual trade value
        valuable_players = sorted_players[:5]  # Top 5 most valuable players
        expendable_players = (
            sorted_players[-5:] if len(sorted_players) > 5 else []
        )  # Bottom 5 least valuable players
        surplus_players = sorted_players[
            :8
        ]  # Top players that could be traded for good value

        # Merge team data with standings data for complete info
        merged_team_data = {**team_data, **standings_team_data}

        team_analysis = {
            "team_info": {
                "team_name": merged_team_data.get("name", f"Team {team_id}"),
                "record": {
                    "wins": merged_team_data.get("wins", 0),
                    "losses": merged_team_data.get("losses", 0),
                },
                "points_for": float(merged_team_data.get("points_for", 0.0)),
                "team_rank": merged_team_data.get("rank", 0),
                "competitive_tier": "competitive",  # Could be calculated based on record
            },
            "roster_analysis": {
                "position_strengths": position_strengths,
                "position_needs": position_needs,
                "surplus_positions": surplus_positions,
            },
            "tradeable_assets": {
                "surplus_players": surplus_players,
                "expendable_players": expendable_players,
                "valuable_players": valuable_players,
                "tradeable_picks": tradeable_picks,
            },
            "trade_strategy": {
                "competitive_analysis": {},
                "trade_preferences": {},
                "recommended_approach": f"Based on roster analysis, consider strengthening {', '.join([pos for pos, need in position_needs.items() if need >= 3])} positions.",
            },
        }

        return {
            "success": True,
            "team_analysis": team_analysis,
            "roster": roster_data,
            "message": f"Found {len(roster_data)} players for {team_analysis['team_info']['team_name']}",
        }

    except Exception as e:
        logger.error(f"🚨 ERROR getting team analysis: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get team analysis: {str(e)}"
        )


@router.post("/api/v1/fantasy/trade-analyzer/recommendations")
async def generate_trade_recommendations(
    request: Dict[str, Any], current_user: dict = Depends(get_current_user)
):
    """Generate AI-powered trade recommendations for a team - REAL DATA ONLY"""
    league_id = request.get("league_id")
    team_id = request.get("team_id")

    logger.info(
        f"🔍 TRADE RECOMMENDATIONS CALLED - League: {league_id}, Team: {team_id}, User: {current_user['user_id']}"
    )

    if not league_id:
        raise HTTPException(status_code=400, detail="league_id is required")

    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        league_doc = await sleeper_service.get_league(str(league_id))
        scoring_type = scoring_type_from_sleeper_league(league_doc)

        recommendations = await generate_sleeper_trade_recommendations(
            sleeper_service=sleeper_service,
            league_id=str(league_id),
            team_id=int(team_id),
            scoring_type=scoring_type,
        )
        if not recommendations:
            user_roster = await fetch_team_roster_players(
                sleeper_service,
                str(league_id),
                int(team_id),
                scoring_type=scoring_type,
            )
            if not user_roster:
                logger.error(
                    "No roster data found for team %s in league %s",
                    team_id,
                    league_id,
                )
                raise HTTPException(
                    status_code=404,
                    detail=f"No roster data found for team {team_id}",
                )

        logger.info("Generated %s trade recommendations", len(recommendations))

        return {
            "success": True,
            "team_id": team_id,
            "league_id": league_id,
            "recommendation_type": request.get("recommendation_type", "all"),
            "recommendation_count": len(recommendations),
            "recommendations": recommendations,
        }

    except Exception as e:
        logger.error(f"🚨 ERROR generating trade recommendations: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate recommendations: {str(e)}"
        )


@router.get("/api/v1/fantasy/trade-analyzer/player-values")
async def get_player_values(
    limit: int = 200,
    league_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Get player trade values for all players"""
    try:
        logger.info(f"Player values called with limit: {limit}")

        # Get Sleeper service for player data
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        all_players = await sleeper_service._get_all_players()
        scoring_type = "ppr"
        if league_id:
            league_doc = await sleeper_service.get_league(str(league_id))
            scoring_type = scoring_type_from_sleeper_league(league_doc)

        # Get trending data for popularity boost
        trending_adds = await sleeper_service.get_trending_players("add")
        trending_lookup = {
            player.get("player_id"): player.get("trend_count", 0)
            for player in trending_adds
        }

        player_values = []

        for player_id, player_data in list(all_players.items())[:limit]:
            if not player_data.get("active", True):
                continue

            name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
            position = player_data.get("position", "UNKNOWN")

            # Skip non-fantasy positions
            if position not in ["QB", "RB", "WR", "TE", "K", "DEF"]:
                continue

            # Calculate trade value
            trade_value = calculate_realistic_trade_value(
                player_data, scoring_type=scoring_type
            )

            # Add trending boost
            trend_count = trending_lookup.get(player_id, 0)
            if trend_count > 0:
                trade_value *= 1 + (
                    trend_count / 100
                )  # Small boost for trending players

            player_values.append(
                {
                    "player_id": player_id,
                    "name": name,
                    "position": position,
                    "team": player_data.get("team", "FA"),
                    "age": player_data.get("age", 27),
                    "trade_value": round(trade_value, 1),
                    "trend_type": "hot" if trend_count > 0 else "neutral",
                    "trend_count": trend_count,
                }
            )

        # Sort by trade value descending
        player_values.sort(key=lambda p: p["trade_value"], reverse=True)

        logger.info(f"Returning {len(player_values)} player values")
        return {
            "success": True,
            "players": player_values,
            "total": len(player_values),
            "limit": limit,
        }

    except Exception as e:
        logger.error(f"Error getting player values: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get player values: {str(e)}"
        )


class QuickAnalysisRequest(BaseModel):
    league_id: str
    team1_id: int
    team2_id: int
    team1_gives: Dict[str, Any]
    team2_gives: Dict[str, Any]


@router.post("/api/v1/fantasy/trade-analyzer/quick-analysis")
async def quick_trade_analysis(
    request: QuickAnalysisRequest, current_user: dict = Depends(get_current_user)
):
    """Perform quick analysis of a proposed trade"""
    try:
        logger.info(
            f"Quick trade analysis called: {request.team1_id} vs {request.team2_id}"
        )

        # Get Sleeper service for player data
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        all_players = await sleeper_service._get_all_players()
        pick_ctx = await load_league_pick_context(
            sleeper_service, str(request.league_id)
        )
        pick_registry = pick_ctx["pick_registry"]
        scoring_type = scoring_type_from_sleeper_league(pick_ctx["league"])

        def analyze_trade_side(assets: Dict[str, Any], side_name: str):
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
                name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
                position = player_data.get("position", "UNKNOWN")
                age = player_data.get("age", 27)
                trade_value = calculate_realistic_trade_value(
                    player_data, scoring_type=scoring_type
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

        # Analyze both sides
        team1_gives = analyze_trade_side(request.team1_gives, "Team 1 Gives")
        team2_gives = analyze_trade_side(request.team2_gives, "Team 2 Gives")

        # Calculate trade fairness
        value_diff = abs(team1_gives["total_value"] - team2_gives["total_value"])
        total_value = team1_gives["total_value"] + team2_gives["total_value"]
        fairness_pct = (
            max(0, 100 - (value_diff / total_value * 100)) if total_value > 0 else 0
        )

        # Determine trade verdict
        if fairness_pct >= 90:
            verdict = "Fair Trade"
            verdict_color = "green"
        elif fairness_pct >= 75:
            verdict = "Slightly Uneven"
            verdict_color = "yellow"
        elif fairness_pct >= 60:
            verdict = "Uneven Trade"
            verdict_color = "orange"
        else:
            verdict = "Very Uneven"
            verdict_color = "red"

        # Generate comprehensive key factors/insights
        insights = []

        # Pick / FAAB analysis
        if team1_gives.get("picks") or team2_gives.get("picks"):
            insights.append(
                "Draft picks included — future value affects dynasty/redraft balance"
            )
        if (team1_gives.get("faab") or 0) > 0 or (team2_gives.get("faab") or 0) > 0:
            insights.append(
                "FAAB included — budget value discounted vs in-season waiver spend"
            )

        # Age analysis
        if team1_gives["avg_age"] > team2_gives["avg_age"] + 3:
            insights.append(
                f"Team 1 trading older players (avg age {team1_gives['avg_age']:.1f} vs {team2_gives['avg_age']:.1f})"
            )
        elif team2_gives["avg_age"] > team1_gives["avg_age"] + 3:
            insights.append(
                f"Team 2 trading older players (avg age {team2_gives['avg_age']:.1f} vs {team1_gives['avg_age']:.1f})"
            )

        # Value differential analysis
        if value_diff > 10:
            if team1_gives["total_value"] > team2_gives["total_value"]:
                insights.append(
                    f"Team 1 giving up {value_diff:.1f} more value - may need compensation"
                )
            else:
                insights.append(
                    f"Team 2 giving up {value_diff:.1f} more value - may need compensation"
                )

        # Player quantity analysis
        if len(team1_gives["players"]) > len(team2_gives["players"]) + 1:
            insights.append(
                "Team 1 trading multiple players for fewer elite players (talent consolidation)"
            )
        elif len(team2_gives["players"]) > len(team1_gives["players"]) + 1:
            insights.append(
                "Team 2 trading multiple players for fewer elite players (talent consolidation)"
            )

        # Position balance analysis
        team1_positions = list(team1_gives["positions"].keys())
        team2_positions = list(team2_gives["positions"].keys())

        if "QB" in team1_positions or "QB" in team2_positions:
            insights.append("QB involved - high-impact position trade")

        if "RB" in team1_positions and "WR" in team2_positions:
            insights.append("RB for WR swap - different positional strategies")
        elif "WR" in team1_positions and "RB" in team2_positions:
            insights.append("WR for RB swap - different positional strategies")

        # High-value player analysis
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

        # Rookie/young player analysis
        team1_young = [p for p in team1_gives["players"] if p["age"] <= 24]
        team2_young = [p for p in team2_gives["players"] if p["age"] <= 24]

        if team1_young and not team2_young:
            insights.append("Team 1 trading young talent for immediate production")
        elif team2_young and not team1_young:
            insights.append("Team 2 trading young talent for immediate production")

        # Ensure we have at least some insights
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

        # Helper function to convert insight strings to structured objects
        def format_insight(insight_text):
            # Determine impact level and category based on content
            impact = "medium"  # default
            category = "general"  # default

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

        # Convert insights to structured format
        structured_insights = [format_insight(insight) for insight in insights]

        trade_seed = (
            f"{request.league_id}:{request.team1_id}:{request.team2_id}:"
            f"{request.team1_gives}:{request.team2_gives}"
        )
        trade_suffix = int(stable_unit(trade_seed) * 1_000_000_000)

        return {
            "success": True,
            "analysis": {
                "trade_id": f"{request.team1_id}_{request.team2_id}_{trade_suffix}",
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
            },
        }

    except Exception as e:
        logger.error(f"Error in quick trade analysis: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze trade: {str(e)}"
        )
