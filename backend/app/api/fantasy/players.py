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
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.service_loader import get_service, is_service_available

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])

from app.api.fantasy.schemas import ComparePlayersRequest


@router.get("/api/fantasy/players/search")
async def search_fantasy_players(
    q: str = None, current_user: dict = Depends(get_current_user)
):
    """Search for fantasy players"""
    try:
        if not q or len(q.strip()) < 2:
            return {
                "status": "success",
                "players": [],
                "message": "Please enter at least 2 characters to search",
            }

        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get all players and filter by search query
        all_players = await sleeper_service._get_all_players()

        search_query = q.lower().strip()
        matching_players = []

        # Search through players for name matches
        for player_id, player_data in all_players.items():
            if not player_data:
                continue

            # Check if search query matches first name, last name, or full name
            first_name = (player_data.get("first_name") or "").lower()
            last_name = (player_data.get("last_name") or "").lower()
            full_name = f"{first_name} {last_name}".strip()

            if (
                search_query in first_name
                or search_query in last_name
                or search_query in full_name
            ):

                # Format player data for frontend
                formatted_player = {
                    "player_id": player_id,
                    "name": (
                        full_name.title()
                        if full_name
                        else player_data.get("full_name", "Unknown")
                    ),
                    "first_name": player_data.get("first_name", ""),
                    "last_name": player_data.get("last_name", ""),
                    "position": player_data.get("position", "N/A"),
                    "team": player_data.get("team", "N/A"),
                    "age": player_data.get("age"),
                    "years_exp": player_data.get("years_exp"),
                    "fantasy_positions": player_data.get("fantasy_positions", []),
                    "status": player_data.get("status", ""),
                    "injury_status": player_data.get("injury_status"),
                }
                matching_players.append(formatted_player)

        # Sort by relevance (exact matches first, then partial matches)
        matching_players.sort(
            key=lambda x: (
                search_query != x["name"].lower(),  # Exact matches first
                x["name"].lower().find(search_query),  # Then by position in name
            )
        )

        # Limit to top 50 results for performance
        matching_players = matching_players[:50]

        return {
            "status": "success",
            "players": matching_players,
            "message": f"Found {len(matching_players)} players matching '{q}'",
        }

    except Exception as e:
        logger.error(f"Error searching players with query '{q}': {e}")
        raise HTTPException(status_code=500, detail="Failed to search fantasy players")


@router.post("/api/fantasy/players/compare")
async def compare_players(
    request: ComparePlayersRequest,
    season: int = Query(2025, ge=2021, le=2030),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare multiple players side-by-side with analytics"""
    try:
        from app.services.fantasy_player_compare import (
            enrich_players_with_analytics,
            generate_compare_insights,
            scoring_type_from_sleeper_league,
        )

        player_ids = request.player_ids
        league_id = request.league_id

        logger.info(
            f"Player comparison called with {len(player_ids)} players: {player_ids}"
        )

        if len(player_ids) < 2 or len(player_ids) > 4:
            raise HTTPException(status_code=400, detail="Must compare 2-4 players")

        # Get Sleeper service for player data
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        all_players = await sleeper_service._get_all_players()

        scoring_type = "ppr"
        league_context: Optional[Dict[str, Any]] = None
        if league_id:
            league_doc = await sleeper_service.get_league(str(league_id))
            scoring_type = scoring_type_from_sleeper_league(league_doc)
            league_context = {
                "league_id": str(league_id),
                "scoring_type": scoring_type,
                "scoring_label": scoring_type.replace("_", " ").upper(),
            }

        # Get trending data
        trending_adds = await sleeper_service.get_trending_players("add")
        trending_drops = await sleeper_service.get_trending_players("drop")
        trending_lookup = {}

        for player in trending_adds:
            trending_lookup[player.get("player_id")] = {
                "type": "hot",
                "count": player.get("trend_count", 0),
            }
        for player in trending_drops:
            if player.get("player_id") not in trending_lookup:
                trending_lookup[player.get("player_id")] = {
                    "type": "cold",
                    "count": player.get("trend_count", 0),
                }

        compared_players = []

        for player_id in player_ids:
            if player_id not in all_players:
                continue

            player_data = all_players[player_id]
            name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()

            # Build comparison data
            comparison_data = {
                "player_id": player_id,
                "name": name,
                "position": player_data.get("position", ""),
                "team": player_data.get("team", ""),
                "age": player_data.get("age"),
                "experience": player_data.get("years_exp"),
                "injury_status": player_data.get("injury_status", "Healthy"),
                "physical_stats": {
                    "height": player_data.get("height"),
                    "weight": player_data.get("weight"),
                },
                "career_info": {
                    "college": player_data.get("college"),
                    "draft_year": player_data.get("draft_year"),
                    "draft_round": player_data.get("draft_round"),
                    "draft_pick": player_data.get("draft_pick"),
                },
                "team_context": {
                    "depth_chart_order": player_data.get("depth_chart_order"),
                    "search_rank": player_data.get("search_rank", 999),
                },
                "trending": trending_lookup.get(
                    player_id, {"type": "normal", "count": 0}
                ),
                "fantasy_positions": player_data.get("fantasy_positions", []),
            }

            compared_players.append(comparison_data)

        players_with_analytics = await enrich_players_with_analytics(
            db, compared_players, season=season, scoring_type=scoring_type
        )
        insights = generate_compare_insights(
            players_with_analytics, scoring_type=scoring_type
        )

        return {
            "status": "success",
            "comparison": {
                "players": players_with_analytics,
                "insights": insights,
                "league_context": league_context,
                "scoring_type": scoring_type,
                "season": season,
                "comparison_date": datetime.utcnow().isoformat(),
            },
        }

    except Exception as e:
        logger.error(f"Error in player comparison: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/fantasy/players/{player_id}/analytics/{season}")
async def get_player_analytics(
    player_id: str,
    season: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player analytics for a specific season"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService

        analytics_service = PlayerAnalyticsService(db)

        # Convert string player_id to int if needed
        try:
            player_id_int = int(player_id)
        except ValueError:
            # If it's a sleeper ID, we would need to map it
            # For now, return a mock response
            return {
                "status": "success",
                "player_id": player_id,
                "season": season,
                "analytics": {
                    "total_points": 0,
                    "avg_points_per_game": 0,
                    "games_played": 0,
                    "consistency_rating": "N/A",
                    "target_share": 0,
                    "red_zone_usage": 0,
                    "snap_percentage": 0,
                },
                "message": "Player analytics data not available",
            }

        # Get week list for the season (weeks 1-17 typically)
        week_list = list(range(1, 18))

        analytics = await analytics_service.get_player_analytics(
            player_id_int, week_list, season
        )

        return {
            "status": "success",
            "player_id": player_id,
            "season": season,
            "analytics": analytics,
        }

    except Exception as e:
        logger.error(f"Error getting player analytics: {str(e)}")
        return {
            "status": "error",
            "message": "Analytics data temporarily unavailable",
            "player_id": player_id,
            "season": season,
            "analytics": {},
        }


@router.get("/api/fantasy/players/{player_id}/trends/{season}")
async def get_player_trends(
    player_id: str,
    season: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player trend analysis for a specific season"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService

        analytics_service = PlayerAnalyticsService(db)

        try:
            player_id_int = int(player_id)
        except ValueError:
            return {
                "status": "success",
                "player_id": player_id,
                "season": season,
                "trends": {
                    "scoring_trend": "stable",
                    "usage_trend": "stable",
                    "efficiency_trend": "stable",
                    "recent_form": "average",
                },
                "message": "Player trends data not available",
            }

        week_list = list(range(1, 18))
        trends = await analytics_service.calculate_usage_trends(
            player_id_int, week_list, season
        )

        return {
            "status": "success",
            "player_id": player_id,
            "season": season,
            "trends": trends,
        }

    except Exception as e:
        logger.error(f"Error getting player trends: {str(e)}")
        return {
            "status": "error",
            "message": "Trends data temporarily unavailable",
            "player_id": player_id,
            "season": season,
            "trends": {},
        }


@router.get("/api/fantasy/players/{player_id}/efficiency/{season}")
async def get_player_efficiency(
    player_id: str,
    season: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player efficiency metrics for a specific season"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService

        analytics_service = PlayerAnalyticsService(db)

        try:
            player_id_int = int(player_id)
        except ValueError:
            return {
                "status": "success",
                "player_id": player_id,
                "season": season,
                "efficiency": {
                    "yards_per_target": 0,
                    "yards_per_carry": 0,
                    "red_zone_efficiency": 0,
                    "target_efficiency": 0,
                    "snap_efficiency": 0,
                },
                "message": "Player efficiency data not available",
            }

        week_list = list(range(1, 18))
        efficiency = await analytics_service.calculate_efficiency_metrics(
            player_id_int, week_list, season
        )

        return {
            "status": "success",
            "player_id": player_id,
            "season": season,
            "efficiency": efficiency,
        }

    except Exception as e:
        logger.error(f"Error getting player efficiency: {str(e)}")
        return {
            "status": "error",
            "message": "Efficiency data temporarily unavailable",
            "player_id": player_id,
            "season": season,
            "efficiency": {},
        }
