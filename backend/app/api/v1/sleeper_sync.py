"""
API endpoints for Sleeper fantasy syncing.

DEPRECATED surface: routes remain for backward compatibility but delegate to the
canonical ``FantasyConnectionService`` / ``fantasy_sleeper_unified`` stack backed
by ``FantasyUser`` (not ``User.sleeper_user_id`` alone).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.services.fantasy_connection_service import fantasy_connection_service
from app.services.fantasy_sleeper_unified import fantasy_sleeper_unified
from app.models.database_models import User
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sleeper", tags=["sleeper"])


async def get_current_db_user(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    user_id = current_user.get("id") or current_user.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


class SleeperConnectRequest(BaseModel):
    sleeper_username: str


class SleeperSyncResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]


@router.post("/connect", response_model=SleeperSyncResponse)
async def connect_sleeper_account(
    request: SleeperConnectRequest,
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    try:
        result = await fantasy_sleeper_unified.connect(
            current_user.id, request.sleeper_username, db=db
        )
        return SleeperSyncResponse(
            success=True,
            message=result["message"],
            data=result,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to connect Sleeper account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Sleeper account",
        )


@router.post("/sync/leagues", response_model=SleeperSyncResponse)
async def sync_league_history(
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    try:
        result = await fantasy_connection_service.sync_all_leagues(current_user.id)
        return SleeperSyncResponse(
            success=True,
            message=result["message"],
            data=result,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to sync league history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync league history",
        )


@router.post("/sync/rosters", response_model=SleeperSyncResponse)
async def sync_all_rosters(
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    """League metadata sync (rosters fetched live from Sleeper during reads)."""
    try:
        result = await fantasy_connection_service.sync_all_leagues(current_user.id)
        return SleeperSyncResponse(
            success=True,
            message=result["message"],
            data={
                **result,
                "total_rosters_synced": result.get("total_synced", 0),
                "leagues_processed": result.get("total_synced", 0),
            },
        )
    except Exception as e:
        logger.error(f"Failed to sync rosters: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync rosters",
        )


@router.post("/sync/players", response_model=SleeperSyncResponse)
async def sync_nfl_players(
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    try:
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can trigger full player sync",
            )

        result = await fantasy_sleeper_unified.sync_fantasy_players(db)
        return SleeperSyncResponse(
            success=True,
            message=(
                f"Synced {result['created']} new and {result['updated']} updated "
                "fantasy players"
            ),
            data=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync NFL players: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync NFL players",
        )


@router.post("/sync/full", response_model=SleeperSyncResponse)
async def full_sleeper_sync(
    request: SleeperConnectRequest,
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    try:
        connect_result = await fantasy_sleeper_unified.connect(
            current_user.id, request.sleeper_username, db=db
        )
        league_result = await fantasy_connection_service.sync_all_leagues(
            current_user.id
        )
        player_result = await fantasy_sleeper_unified.sync_fantasy_players(db)

        return SleeperSyncResponse(
            success=True,
            message="Full Sleeper sync completed successfully",
            data={
                "connect": connect_result,
                "leagues": league_result,
                "players": player_result,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to complete full sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete full sync",
        )


@router.get("/status", response_model=Dict[str, Any])
async def get_sleeper_sync_status(
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    try:
        return await fantasy_sleeper_unified.get_sync_status(current_user.id, db)
    except Exception as e:
        logger.error(f"Failed to get sync status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get sync status",
        )


@router.get("/leagues", response_model=List[Dict[str, Any]])
async def get_user_leagues(
    current_user: User = Depends(get_current_db_user),
    db: Session = Depends(get_db),
):
    try:
        result = await fantasy_connection_service.get_user_leagues(current_user.id)
        return result.get("leagues", [])
    except Exception as e:
        logger.error(f"Failed to get user leagues: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user leagues",
        )


@router.get("/leagues/{league_id}/rosters", response_model=List[Dict[str, Any]])
async def get_league_rosters(
    league_id: str,
    current_user: User = Depends(get_current_db_user),
):
    try:
        return await fantasy_sleeper_unified.get_league_rosters_from_sleeper(league_id)
    except Exception as e:
        logger.error(f"Failed to get league rosters: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get league rosters",
        )


@router.get("/leagues/{league_id}/rules")
async def get_league_rules_compat(
    league_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Compatibility shim for frontend fallback to ``/api/sleeper/leagues/{id}/rules``."""
    from app.services.sleeper_fantasy_service import SleeperFantasyService

    try:
        sleeper_service = SleeperFantasyService()
        league_details = await sleeper_service.get_league_details(league_id)
        return {"status": "success", "rules": league_details}
    except Exception as e:
        logger.error(f"Failed to get league rules for {league_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch league rules",
        )
