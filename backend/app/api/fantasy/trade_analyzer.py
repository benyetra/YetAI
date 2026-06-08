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
    calculate_realistic_trade_value,
    load_league_pick_context,
    format_roster_traded_picks,
)
from app.services.fantasy_player_compare import scoring_type_from_sleeper_league
from app.services.fantasy_sleeper_roster import fetch_team_roster_players
from app.services.fantasy_sleeper_trade_proposal import (
    evaluate_sleeper_trade,
    propose_sleeper_trade,
)
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


class ProposeTradeRequest(BaseModel):
    league_id: str
    team1_id: int
    team2_id: int
    team1_gives: Dict[str, Any]
    team2_gives: Dict[str, Any]
    trade_reason: Optional[str] = None
    persist: bool = False


@router.post("/api/v1/fantasy/trade-analyzer/quick-analysis")
async def quick_trade_analysis(
    request: QuickAnalysisRequest, current_user: dict = Depends(get_current_user)
):
    """Perform quick analysis of a proposed trade"""
    try:
        logger.info(
            f"Quick trade analysis called: {request.team1_id} vs {request.team2_id}"
        )

        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        analysis = await evaluate_sleeper_trade(
            sleeper_service=sleeper_service,
            platform_league_id=str(request.league_id),
            team1_roster_id=request.team1_id,
            team2_roster_id=request.team2_id,
            team1_gives=request.team1_gives,
            team2_gives=request.team2_gives,
        )

        return {"success": True, "analysis": analysis}

    except Exception as e:
        logger.error(f"Error in quick trade analysis: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze trade: {str(e)}"
        )


@router.post("/api/v1/fantasy/trade-analyzer/propose")
async def propose_trade(
    request: ProposeTradeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate and evaluate a Sleeper trade proposal (optional DB persist)."""
    try:
        logger.info(
            "Propose trade called: league=%s team1=%s team2=%s user=%s",
            request.league_id,
            request.team1_id,
            request.team2_id,
            current_user["user_id"],
        )

        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        result = await propose_sleeper_trade(
            sleeper_service=sleeper_service,
            platform_league_id=str(request.league_id),
            team1_roster_id=request.team1_id,
            team2_roster_id=request.team2_id,
            team1_gives=request.team1_gives,
            team2_gives=request.team2_gives,
            trade_reason=request.trade_reason,
            persist=request.persist,
            db=db if request.persist else None,
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "Invalid trade")
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error proposing trade: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to propose trade: {str(e)}"
        )
