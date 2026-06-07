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

from app.api.fantasy.schemas import FantasyConnectRequest


@router.options("/api/fantasy/accounts")
async def options_fantasy_accounts():
    """Handle CORS preflight for fantasy accounts"""
    return {}


@router.get("/api/fantasy/accounts")
async def get_fantasy_accounts(current_user: dict = Depends(get_current_user)):
    """Get connected fantasy accounts"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.get_user_connections(
            current_user.get("id") or current_user.get("user_id")
        )
        return result
    except Exception as e:
        logger.error(
            f"Error getting fantasy accounts for user {current_user['user_id']}: {e}"
        )
        raise HTTPException(status_code=500, detail="Failed to get fantasy accounts")


@router.options("/api/fantasy/leagues")
async def options_fantasy_leagues():
    """Handle CORS preflight for fantasy leagues"""
    return {}


@router.get("/api/fantasy/leagues")
async def get_fantasy_leagues(current_user: dict = Depends(get_current_user)):
    """Get fantasy leagues for user"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.get_user_leagues(
            current_user.get("id") or current_user.get("user_id")
        )
        return result
    except Exception as e:
        logger.error(
            f"Error getting fantasy leagues for user {current_user['user_id']}: {e}"
        )
        raise HTTPException(status_code=500, detail="Failed to get fantasy leagues")


@router.options("/api/fantasy/connect")
async def options_fantasy_connect():
    """Handle CORS preflight for fantasy platform connection"""
    return {}


@router.post("/api/fantasy/connect")
async def connect_fantasy_platform(
    connect_request: FantasyConnectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Connect to a fantasy platform (Sleeper, ESPN, etc.)"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.connect_platform(
            user_id=current_user.get("id") or current_user.get("user_id"),
            platform=connect_request.platform,
            credentials=connect_request.credentials,
        )
        return result
    except ValueError as e:
        logger.error(f"Validation error connecting to {connect_request.platform}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error connecting to {connect_request.platform}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to {connect_request.platform}: {str(e)}",
        )


@router.options("/api/fantasy/sync-league/{league_id}")
async def options_fantasy_sync_league():
    """Handle CORS preflight for fantasy league sync"""
    return {}


@router.post("/api/fantasy/sync-league/{league_id}")
async def sync_fantasy_league(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Sync a Sleeper league into FantasyLeague metadata."""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        return await fantasy_connection_service.sync_league(
            user_id=current_user.get("id") or current_user.get("user_id"),
            league_id=league_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error syncing fantasy league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync fantasy league")


@router.options("/api/fantasy/roster/{league_id}")
async def options_fantasy_roster():
    """Handle CORS preflight for fantasy roster"""
    return {}


@router.get("/api/fantasy/roster/{league_id}")
async def get_fantasy_roster(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Get fantasy roster for a specific league - REAL DATA ONLY"""
    logger.info(
        f"🔍 ROSTER ENDPOINT CALLED - League: {league_id}, User: {current_user['user_id']}"
    )

    service_available = is_service_available("fantasy_pipeline")
    logger.info(f"🔍 FANTASY_PIPELINE SERVICE AVAILABLE: {service_available}")

    if not service_available:
        logger.error("🚨 FANTASY_PIPELINE SERVICE NOT AVAILABLE")
        raise HTTPException(
            status_code=503, detail="Fantasy pipeline service unavailable"
        )

    try:
        fantasy_service = get_service("fantasy_pipeline")
        logger.info(
            f"🔍 CALLING get_league_roster with league_id={league_id}, user_id={current_user['user_id']}"
        )
        roster = await fantasy_service.get_league_roster(
            league_id, current_user.get("id") or current_user.get("user_id")
        )
        logger.info(f"🔍 ROSTER RETRIEVED: {len(roster)} players")

        if not roster:
            logger.error(
                f"🚨 NO ROSTER DATA FOUND for league {league_id}, user {current_user['user_id']}"
            )
            raise HTTPException(
                status_code=404, detail="No roster data found for this league and user"
            )

        return {"status": "success", "roster": roster}
    except Exception as e:
        logger.error(f"🚨 ERROR fetching roster for league {league_id}: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch roster: {str(e)}")


@router.get("/api/fantasy/projections")
async def get_fantasy_projections(
    current_user: dict = Depends(get_current_user), db=Depends(get_db)
):
    """Get fantasy projections - REAL DATA ONLY"""
    logger.info(f"🔍 PROJECTIONS CALLED - User: {current_user['user_id']}")

    service_available = is_service_available("fantasy_pipeline")
    logger.info(f"🔍 FANTASY_PIPELINE SERVICE AVAILABLE: {service_available}")

    if not service_available:
        logger.error("🚨 FANTASY_PIPELINE SERVICE NOT AVAILABLE")
        raise HTTPException(
            status_code=503, detail="Fantasy pipeline service unavailable"
        )

    try:
        fantasy_service = get_service("fantasy_pipeline")

        # Get real NFL players and generate projections from analytics/baselines
        players = await fantasy_service.get_nfl_players(limit=50)

        if not players:
            logger.error("🚨 NO PLAYER DATA AVAILABLE")
            raise HTTPException(status_code=404, detail="No player data available")

        from datetime import datetime

        season = datetime.now().year
        projections = fantasy_service.generate_fantasy_projections(
            players, games=[], db=db, season=season
        )

        logger.info(f"🔍 GENERATED {len(projections)} PROJECTIONS")

        return {"status": "success", "projections": projections}

    except Exception as e:
        logger.error(f"🚨 ERROR fetching fantasy projections: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch projections: {str(e)}"
        )


@router.options("/api/fantasy/disconnect/{fantasy_user_id}")
async def options_disconnect_fantasy_account():
    """Handle CORS preflight for fantasy account disconnect"""
    return {}


@router.delete("/api/fantasy/disconnect/{fantasy_user_id}")
async def disconnect_fantasy_account(
    fantasy_user_id: str, current_user: dict = Depends(get_current_user)
):
    """Disconnect a fantasy sports account"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.disconnect_platform(
            user_id=current_user.get("id") or current_user.get("user_id"),
            platform_user_id=fantasy_user_id,
        )
        return result
    except Exception as e:
        logger.error(
            f"Error disconnecting fantasy account {fantasy_user_id} for user {current_user['user_id']}: {e}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to disconnect fantasy account"
        )


@router.get("/api/v1/fantasy/standings/{league_id}")
async def get_fantasy_standings(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Get fantasy league standings"""
    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get league teams (which includes standings data)
        teams = await sleeper_service.get_league_teams(league_id)

        # Sort teams by wins, then points for
        standings = sorted(
            teams,
            key=lambda x: (x.get("wins", 0), x.get("points_for", 0)),
            reverse=True,
        )

        # Add ranking
        for i, team in enumerate(standings):
            team["rank"] = i + 1

        return {
            "status": "success",
            "standings": standings,
            "message": f"Retrieved standings for {len(standings)} teams",
        }
    except Exception as e:
        logger.error(f"Error getting standings for league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get fantasy standings")
