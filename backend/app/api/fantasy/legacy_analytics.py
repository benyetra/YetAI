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
from app.core.service_loader import get_service, is_service_available

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])


# Analytics endpoints with frontend-compatible URLs
@router.get("/api/fantasy/analytics/{player_id}")
async def get_player_analytics_alt(
    player_id: str,
    season: int = 2025,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player analytics (alternative URL format)"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        analytics_service = PlayerAnalyticsService(db)

        # Map Sleeper player ID to internal player ID
        internal_player_id = None
        try:
            # Query database for the mapping
            fantasy_player_query = db.execute(
                text(
                    "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
                ),
                {"sleeper_id": str(player_id)},
            )
            fantasy_player_row = fantasy_player_query.fetchone()

            if fantasy_player_row:
                internal_player_id = fantasy_player_row[0]
                logger.info(
                    f"Mapped Sleeper ID {player_id} to internal ID {internal_player_id}"
                )
            else:
                logger.warning(f"No mapping found for Sleeper ID {player_id}")

        except Exception as e:
            logger.warning(f"Error mapping player ID {player_id}: {e}")

        analytics = []
        if internal_player_id:
            analytics = await analytics_service.get_player_analytics(
                internal_player_id, season=season
            )

        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "analytics": analytics or [],
        }
    except Exception as e:
        logger.error(f"Error getting player analytics for {player_id}: {e}")
        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "analytics": [],
        }


@router.get("/api/fantasy/analytics/{player_id}/trends")
async def get_player_trends_alt(
    player_id: str,
    season: int = 2025,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player trends (alternative URL format)"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        # Map Sleeper player ID to internal ID
        fantasy_player_query = db.execute(
            text(
                "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
            ),
            {"sleeper_id": str(player_id)},
        )
        fantasy_player = fantasy_player_query.fetchone()

        if not fantasy_player:
            return {
                "status": "error",
                "message": f"Player not found with ID: {player_id}",
                "trends": {},
            }

        internal_player_id = fantasy_player[0]
        analytics_service = PlayerAnalyticsService(db)

        # Get analytics and derive trends
        analytics = await analytics_service.get_player_analytics(
            internal_player_id, season=season
        )

        trends = {}
        if analytics and len(analytics) >= 2:
            recent = analytics[:3]  # Last 3 games
            older = analytics[3:6]  # Previous 3 games

            if recent and older:
                recent_avg = sum(g.get("ppr_points", 0) for g in recent) / len(recent)
                older_avg = sum(g.get("ppr_points", 0) for g in older) / len(older)

                trends = {
                    "trend_direction": "up" if recent_avg > older_avg else "down",
                    "recent_avg": round(recent_avg, 1),
                    "previous_avg": round(older_avg, 1),
                    "games_analyzed": len(recent) + len(older),
                }

        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "trends": trends,
        }
    except Exception as e:
        logger.error(f"Error getting player trends for {player_id}: {e}")
        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "trends": {},
        }


@router.get("/api/fantasy/analytics/{player_id}/efficiency")
async def get_player_efficiency_alt(
    player_id: str,
    season: int = 2025,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player efficiency (alternative URL format)"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        # Map Sleeper player ID to internal ID
        fantasy_player_query = db.execute(
            text(
                "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
            ),
            {"sleeper_id": str(player_id)},
        )
        fantasy_player = fantasy_player_query.fetchone()

        if not fantasy_player:
            return {
                "status": "error",
                "message": f"Player not found with ID: {player_id}",
                "efficiency": {},
            }

        internal_player_id = fantasy_player[0]
        analytics_service = PlayerAnalyticsService(db)

        # Get analytics and calculate efficiency metrics
        analytics = await analytics_service.get_player_analytics(
            internal_player_id, season=season
        )

        efficiency = {}
        if analytics:
            total_points = sum(g.get("ppr_points", 0) for g in analytics)
            total_snaps = sum(g.get("snaps") or 0 for g in analytics)
            total_targets = sum(g.get("targets") or 0 for g in analytics)

            if total_snaps > 0:
                efficiency["points_per_snap"] = round(total_points / total_snaps, 2)
            if total_targets > 0:
                efficiency["points_per_target"] = round(total_points / total_targets, 2)

            efficiency["games_played"] = len(analytics)
            efficiency["total_points"] = round(total_points, 1)

        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "efficiency": efficiency,
        }
    except Exception as e:
        logger.error(f"Error getting player efficiency for {player_id}: {e}")
        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "efficiency": {},
        }
