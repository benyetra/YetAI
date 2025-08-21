"""
Fantasy Sports API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

from app.core.database import get_db
from app.services.fantasy_service import FantasyService
from app.services.sleeper_fantasy_service import SleeperFantasyService
from app.models.fantasy_models import FantasyPlatform
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models for request/response
class ConnectAccountRequest(BaseModel):
    platform: FantasyPlatform
    credentials: Dict[str, Any]

class ConnectAccountResponse(BaseModel):
    success: bool
    message: str
    fantasy_user_id: Optional[int] = None
    error: Optional[str] = None

class FantasyAccountInfo(BaseModel):
    id: int
    platform: FantasyPlatform
    username: Optional[str]
    last_sync: Optional[str]
    league_count: int

class FantasyLeagueInfo(BaseModel):
    id: int
    name: str
    platform: FantasyPlatform
    season: int
    team_count: Optional[int]
    scoring_type: Optional[str]
    last_sync: Optional[str]
    user_team: Optional[Dict[str, Any]]

class StartSitRecommendation(BaseModel):
    league_id: int
    league_name: str
    player_name: str
    position: str
    recommendation: str  # START or SIT
    projected_points: float
    confidence: float
    reasoning: Optional[str]

class WaiverWireRecommendation(BaseModel):
    league_id: int
    league_name: str
    player_name: str
    position: str
    opportunity_score: float
    ownership_percentage: Optional[float]
    reason: str
    suggested_fab_percentage: Optional[float]
    rest_of_season_value: Optional[float]

# Initialize fantasy service
fantasy_service = None

def get_fantasy_service(db: Session = Depends(get_db)) -> FantasyService:
    """Get fantasy service with registered platforms"""
    global fantasy_service
    
    if fantasy_service is None:
        fantasy_service = FantasyService(db)
        # Register platform interfaces
        fantasy_service.register_platform(FantasyPlatform.SLEEPER, SleeperFantasyService())
        # TODO: Add Yahoo and ESPN services when implemented
    
    # Update database session (since it changes per request)
    fantasy_service.db = db
    return fantasy_service

@router.post("/connect", response_model=ConnectAccountResponse)
async def connect_fantasy_account(
    request: ConnectAccountRequest,
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Connect a user's fantasy sports account"""
    try:
        result = await fantasy_service.connect_user_account(
            user_id=current_user["id"],
            platform=request.platform,
            credentials=request.credentials
        )
        
        if result["success"]:
            return ConnectAccountResponse(
                success=True,
                message=f"Successfully connected {request.platform} account",
                fantasy_user_id=result["fantasy_user_id"]
            )
        else:
            return ConnectAccountResponse(
                success=False,
                message="Failed to connect account",
                error=result.get("error")
            )
            
    except Exception as e:
        logger.error(f"Error connecting fantasy account: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accounts")
async def get_fantasy_accounts(
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get all connected fantasy accounts for the user"""
    try:
        accounts = fantasy_service.get_user_fantasy_accounts(current_user["id"])
        
        # Format for frontend compatibility
        formatted_accounts = [
            {
                "id": str(account["id"]),
                "platform": account["platform"],
                "username": account["username"],
                "user_id": str(current_user["id"]),
                "is_active": True,  # All active accounts since we filter inactive ones
                "last_sync": account["last_sync"].isoformat() if account["last_sync"] else None,
                "created_at": None,  # Not available in current model
                "league_count": account["league_count"]
            }
            for account in accounts
        ]
        
        return {
            "status": "success",
            "accounts": formatted_accounts
        }
        
    except Exception as e:
        logger.error(f"Error getting fantasy accounts: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "accounts": []
        }

@router.get("/leagues")
async def get_fantasy_leagues(
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get all fantasy leagues for the user"""
    try:
        leagues = fantasy_service.get_user_leagues(current_user["id"])
        print(f"DEBUG: leagues from service: {leagues}")
        
        # Format for frontend compatibility
        formatted_leagues = [
            {
                "id": str(league["id"]),
                "league_id": league["platform_league_id"],  # Use platform league ID for Trade Analyzer
                "name": league["name"],
                "platform": league["platform"],
                "season": str(league["season"]),  # Frontend expects string
                "total_teams": league["team_count"],  # Frontend expects this field name
                "team_count": league["team_count"],  # Keep for backward compatibility
                "scoring_type": league["scoring_type"],
                "settings": {"scoring_type": league["scoring_type"]},  # Frontend expects this
                "last_sync": league["last_sync"].isoformat() if league["last_sync"] else None,
                "is_active": True,  # All synced leagues are active
                "user_team": league["user_team"]
            }
            for league in leagues
        ]
        
        return {
            "status": "success", 
            "leagues": formatted_leagues
        }
        
    except Exception as e:
        logger.error(f"Error getting fantasy leagues: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "leagues": []
        }

@router.get("/leagues/{league_id}/rules")
async def get_league_rules(
    league_id: str,
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get detailed league rules and settings for AI recommendations"""
    try:
        # Verify user has access to this league
        leagues = fantasy_service.get_user_leagues(current_user["id"])
        league = next((l for l in leagues if str(l["id"]) == league_id), None)
        
        if not league:
            raise HTTPException(status_code=404, detail="League not found or not accessible")
        
        # Get the platform service to fetch detailed rules
        platform_service = None
        if league["platform"] == "sleeper":
            platform_service = SleeperFantasyService()
        else:
            raise HTTPException(status_code=400, detail=f"Platform {league['platform']} not supported for detailed rules")
        
        # Get detailed league data from platform
        league_details = await platform_service.get_league_details(league["platform_league_id"])
        
        if not league_details:
            raise HTTPException(status_code=404, detail="League details not found on platform")
        
        # Extract and format league rules
        scoring_settings = league_details.get('scoring_settings', {})
        roster_positions = league_details.get('roster_positions', [])
        
        # Determine league type based on settings
        league_type = "Redraft"  # Default
        if 'keeper_deadline' in league_details or league_details.get('type') == 2:
            league_type = "Keeper"
        elif league_details.get('type') == 1:
            league_type = "Dynasty"
        
        # Count roster positions
        roster_counts = {}
        for pos in roster_positions:
            roster_counts[pos] = roster_counts.get(pos, 0) + 1
        
        # Calculate total roster size
        total_roster_size = len(roster_positions)
        bench_spots = roster_counts.get('BN', 0)
        starting_spots = total_roster_size - bench_spots
        
        # Determine scoring type with more detail
        scoring_type = "Standard"
        ppr_value = scoring_settings.get('rec', 0)
        if ppr_value >= 1:
            scoring_type = f"Full PPR ({ppr_value} pt/rec)"
        elif ppr_value >= 0.5:
            scoring_type = f"Half PPR ({ppr_value} pt/rec)"
        elif ppr_value > 0:
            scoring_type = f"Fractional PPR ({ppr_value} pt/rec)"
        
        # Additional scoring details
        passing_tds = scoring_settings.get('pass_td', 0)
        passing_yards = scoring_settings.get('pass_yd', 0)
        rushing_tds = scoring_settings.get('rush_td', 0) 
        rushing_yards = scoring_settings.get('rush_yd', 0)
        receiving_tds = scoring_settings.get('rec_td', 0)
        receiving_yards = scoring_settings.get('rec_yd', 0)
        
        # Check for special scoring
        special_scoring = []
        if scoring_settings.get('bonus_pass_yd_300', 0) > 0:
            special_scoring.append(f"300+ Pass Yards: +{scoring_settings['bonus_pass_yd_300']} pts")
        if scoring_settings.get('bonus_rush_yd_100', 0) > 0:
            special_scoring.append(f"100+ Rush Yards: +{scoring_settings['bonus_rush_yd_100']} pts")
        if scoring_settings.get('bonus_rec_yd_100', 0) > 0:
            special_scoring.append(f"100+ Rec Yards: +{scoring_settings['bonus_rec_yd_100']} pts")
        
        # Format rules response
        rules = {
            "league_id": league_id,
            "league_name": league["name"],
            "platform": league["platform"],
            "season": league["season"],
            "league_type": league_type,
            "team_count": league["team_count"],
            
            # Roster Settings
            "roster_settings": {
                "total_spots": total_roster_size,
                "starting_spots": starting_spots,
                "bench_spots": bench_spots,
                "positions": roster_counts,
                "position_requirements": roster_positions
            },
            
            # Scoring Settings
            "scoring_settings": {
                "type": scoring_type,
                "passing": {
                    "touchdowns": passing_tds,
                    "yards_per_point": 1/passing_yards if passing_yards > 0 else 0,
                    "interceptions": scoring_settings.get('pass_int', 0)
                },
                "rushing": {
                    "touchdowns": rushing_tds,
                    "yards_per_point": 1/rushing_yards if rushing_yards > 0 else 0,
                    "fumbles": scoring_settings.get('fum_lost', 0)
                },
                "receiving": {
                    "touchdowns": receiving_tds,
                    "yards_per_point": 1/receiving_yards if receiving_yards > 0 else 0,
                    "receptions": ppr_value
                },
                "special_scoring": special_scoring,
                "raw_settings": scoring_settings
            },
            
            # League Features
            "features": {
                "trades_enabled": league_details.get('settings', {}).get('trade_deadline', None) is not None,
                "waivers_enabled": True,  # Assume enabled for most leagues
                "playoffs": {
                    "teams": league_details.get('settings', {}).get('playoff_teams', 6),
                    "weeks": league_details.get('settings', {}).get('playoff_week_start', 15)
                }
            },
            
            # AI Recommendation Context
            "ai_context": {
                "prioritize_volume": ppr_value > 0,  # PPR leagues favor target volume
                "rb_premium": ppr_value < 0.5,  # Standard/half-PPR favors RBs more
                "flex_strategy": "FLEX" in roster_positions or "W/R/T" in roster_positions,
                "superflex": "SUPER_FLEX" in roster_positions,
                "position_scarcity": {
                    "qb": roster_counts.get('QB', 1),
                    "rb": roster_counts.get('RB', 2), 
                    "wr": roster_counts.get('WR', 2),
                    "te": roster_counts.get('TE', 1),
                    "flex": roster_counts.get('FLEX', 0) + roster_counts.get('W/R/T', 0)
                }
            }
        }
        
        return {
            "status": "success",
            "rules": rules
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting league rules for league {league_id}: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "rules": None
        }

@router.post("/sync/{fantasy_user_id}")
async def sync_fantasy_leagues(
    fantasy_user_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Manually sync leagues for a fantasy account"""
    try:
        # Verify the fantasy user belongs to current user
        accounts = fantasy_service.get_user_fantasy_accounts(current_user["id"])
        if not any(acc["id"] == fantasy_user_id for acc in accounts):
            raise HTTPException(status_code=403, detail="Fantasy account not found or not owned by user")
        
        # Run sync in background
        background_tasks.add_task(fantasy_service.sync_user_leagues, fantasy_user_id)
        
        return {"success": True, "message": "Sync started in background"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing fantasy leagues: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/disconnect/{fantasy_user_id}")
async def disconnect_fantasy_account(
    fantasy_user_id: int,
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Disconnect a fantasy sports account"""
    try:
        result = fantasy_service.disconnect_fantasy_account(current_user["id"], fantasy_user_id)
        
        if result["success"]:
            return {"success": True, "message": "Fantasy account disconnected successfully"}
        else:
            return {"success": False, "error": result.get("error")}
            
    except Exception as e:
        logger.error(f"Error disconnecting fantasy account: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recommendations/start-sit", response_model=List[StartSitRecommendation])
async def get_start_sit_recommendations(
    week: int,
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get start/sit recommendations for the current week"""
    try:
        recommendations = await fantasy_service.generate_start_sit_recommendations(
            current_user["id"], week
        )
        
        return [
            StartSitRecommendation(
                league_id=rec["league_id"],
                league_name=rec["league_name"],
                player_name=rec["player_name"],
                position=rec["position"],
                recommendation=rec["recommendation"],
                projected_points=rec["projected_points"],
                confidence=rec["confidence"],
                reasoning=rec["reasoning"]
            )
            for rec in recommendations
        ]
        
    except Exception as e:
        logger.error(f"Error getting start/sit recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recommendations/waiver-wire", response_model=List[WaiverWireRecommendation])
async def get_waiver_wire_recommendations(
    week: int,
    current_user: dict = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get waiver wire pickup recommendations"""
    try:
        recommendations = await fantasy_service.generate_waiver_wire_recommendations(
            current_user["id"], week
        )
        
        return [
            WaiverWireRecommendation(
                league_id=rec["league_id"],
                league_name=rec["league_name"],
                player_name=rec["player_name"],
                position=rec["position"],
                opportunity_score=rec["opportunity_score"],
                ownership_percentage=rec["ownership_percentage"],
                reason=rec["reason"],
                suggested_fab_percentage=rec["suggested_fab_percentage"],
                rest_of_season_value=rec["rest_of_season_value"]
            )
            for rec in recommendations
        ]
        
    except Exception as e:
        logger.error(f"Error getting waiver wire recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/test/sleeper-user/{username}")
async def test_sleeper_user(username: str):
    """Test endpoint to verify Sleeper API integration"""
    try:
        sleeper_service = SleeperFantasyService()
        
        # Test authentication
        auth_result = await sleeper_service.authenticate_user({"username": username})
        
        # Test getting leagues
        leagues = await sleeper_service.get_user_leagues(auth_result["user_id"])
        
        return {
            "user": auth_result,
            "leagues_count": len(leagues),
            "leagues": leagues[:3]  # Return first 3 leagues for testing
        }
        
    except Exception as e:
        logger.error(f"Error testing Sleeper integration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/test/sleeper-trending")
async def test_sleeper_trending():
    """Test endpoint for Sleeper trending players"""
    try:
        sleeper_service = SleeperFantasyService()
        
        # Get trending adds and drops
        trending_adds = await sleeper_service.get_trending_players("add")
        trending_drops = await sleeper_service.get_trending_players("drop")
        
        return {
            "trending_adds": trending_adds[:10],
            "trending_drops": trending_drops[:10]
        }
        
    except Exception as e:
        logger.error(f"Error testing Sleeper trending: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))