"""
API endpoints for simplified Sleeper fantasy syncing
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import logging

from app.core.database import get_db
from app.main import get_current_user
from app.services.simplified_sleeper_service import SimplifiedSleeperService
from app.models.database_models import User, SleeperLeague, SleeperRoster, SleeperPlayer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sleeper", tags=["sleeper_sync"])

class SleeperConnectRequest(BaseModel):
    sleeper_username: str

class SleeperSyncResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

sleeper_service = SimplifiedSleeperService()

@router.post("/connect", response_model=SleeperSyncResponse)
async def connect_sleeper_account(
    request: SleeperConnectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Connect a Sleeper account by username
    This gets the SleeperUserID and saves it to the user record
    """
    try:
        result = await sleeper_service.connect_sleeper_account(
            current_user.id, 
            request.sleeper_username, 
            db
        )
        
        return SleeperSyncResponse(
            success=True,
            message=f"Successfully connected Sleeper account: {request.sleeper_username}",
            data=result
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to connect Sleeper account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Sleeper account"
        )

@router.post("/sync/leagues", response_model=SleeperSyncResponse)
async def sync_league_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sync all league history from 2020-2025
    Requires user to have connected Sleeper account first
    """
    try:
        if not current_user.sleeper_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must connect Sleeper account first"
            )
        
        result = await sleeper_service.sync_all_league_history(current_user.id, db)
        
        return SleeperSyncResponse(
            success=True,
            message=f"Successfully synced {result['total_synced']} leagues",
            data=result
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to sync league history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync league history"
        )

@router.post("/sync/rosters", response_model=SleeperSyncResponse)
async def sync_all_rosters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sync all rosters for all user's leagues
    """
    try:
        result = await sleeper_service.sync_all_rosters(current_user.id, db)
        
        return SleeperSyncResponse(
            success=True,
            message=f"Successfully synced {result['total_rosters_synced']} rosters across {result['leagues_processed']} leagues",
            data=result
        )
        
    except Exception as e:
        logger.error(f"Failed to sync rosters: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync rosters"
        )

@router.post("/sync/players", response_model=SleeperSyncResponse)
async def sync_nfl_players(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sync all NFL player data
    Note: This syncs players for the entire system, not just one user
    """
    try:
        # Only allow admins to trigger full player sync to avoid overload
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can trigger full player sync"
            )
        
        result = await sleeper_service.sync_nfl_players(db)
        
        return SleeperSyncResponse(
            success=True,
            message=f"Successfully synced {result['new_players']} new players and updated {result['updated_players']} existing players",
            data=result
        )
        
    except Exception as e:
        logger.error(f"Failed to sync NFL players: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync NFL players"
        )

@router.post("/sync/full", response_model=SleeperSyncResponse)
async def full_sleeper_sync(
    request: SleeperConnectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Complete workflow: Connect account -> Sync leagues -> Sync rosters -> Sync players
    """
    try:
        result = await sleeper_service.full_sync_workflow(
            current_user.id,
            request.sleeper_username,
            db
        )
        
        return SleeperSyncResponse(
            success=True,
            message="Full Sleeper sync completed successfully",
            data=result
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to complete full sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete full sync"
        )

@router.get("/status", response_model=Dict[str, Any])
async def get_sleeper_sync_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current Sleeper sync status for the user
    """
    try:
        # Get user's Sleeper connection status
        sleeper_connected = bool(current_user.sleeper_user_id)
        
        # Get league count
        league_count = db.query(SleeperLeague).filter(SleeperLeague.user_id == current_user.id).count()
        
        # Get roster count
        roster_count = db.query(SleeperRoster).join(SleeperLeague).filter(SleeperLeague.user_id == current_user.id).count()
        
        # Get total player count in system
        player_count = db.query(SleeperPlayer).count()
        
        return {
            "sleeper_connected": sleeper_connected,
            "sleeper_user_id": current_user.sleeper_user_id,
            "leagues_synced": league_count,
            "rosters_synced": roster_count,
            "total_players_in_system": player_count,
            "last_sync": None  # TODO: Add last sync timestamp tracking
        }
        
    except Exception as e:
        logger.error(f"Failed to get sync status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get sync status"
        )

@router.get("/leagues", response_model=List[Dict[str, Any]])
async def get_user_leagues(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all synced leagues for the current user
    """
    try:
        leagues = db.query(SleeperLeague).filter(SleeperLeague.user_id == current_user.id).all()
        
        return [
            {
                "id": league.id,
                "sleeper_league_id": league.sleeper_league_id,
                "name": league.name,
                "season": league.season,
                "total_rosters": league.total_rosters,
                "status": league.status,
                "scoring_type": league.scoring_type,
                "last_synced": league.last_synced.isoformat() if league.last_synced else None
            }
            for league in leagues
        ]
        
    except Exception as e:
        logger.error(f"Failed to get user leagues: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user leagues"
        )

@router.get("/leagues/{league_id}/rosters", response_model=List[Dict[str, Any]])
async def get_league_rosters(
    league_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all rosters for a specific league
    """
    try:
        # Verify user owns this league
        league = db.query(SleeperLeague).filter(
            SleeperLeague.id == league_id,
            SleeperLeague.user_id == current_user.id
        ).first()
        
        if not league:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="League not found"
            )
        
        rosters = db.query(SleeperRoster).filter(SleeperRoster.league_id == league_id).all()
        
        return [
            {
                "id": roster.id,
                "sleeper_roster_id": roster.sleeper_roster_id,
                "sleeper_owner_id": roster.sleeper_owner_id,
                "team_name": roster.team_name,
                "owner_name": roster.owner_name,
                "wins": roster.wins,
                "losses": roster.losses,
                "ties": roster.ties,
                "points_for": roster.points_for,
                "points_against": roster.points_against,
                "waiver_position": roster.waiver_position,
                "player_count": len(roster.players) if roster.players else 0,
                "last_synced": roster.last_synced.isoformat() if roster.last_synced else None
            }
            for roster in rosters
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get league rosters: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get league rosters"
        )