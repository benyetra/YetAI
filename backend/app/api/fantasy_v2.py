"""
Fantasy API V2 - Streamlined endpoints using new schema
Simple, efficient API with minimal complexity
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.fantasy_service_v2 import FantasyServiceV2
from app.models.database_models import User
from app.models.fantasy_models_v2 import League, Team, Player
from app.core.auth import get_current_user
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/fantasy", tags=["Fantasy V2"])

@router.get("/leagues")
async def get_user_leagues(
    season: Optional[int] = Query(None, description="Filter by season"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all leagues for the current user"""
    try:
        service = FantasyServiceV2(db)
        leagues = service.get_user_leagues(current_user.id, season)
        
        return {
            "success": True,
            "leagues": [
                {
                    "id": league.id,
                    "name": league.name,
                    "platform": league.platform,
                    "external_league_id": league.external_league_id,
                    "season": league.season,
                    "total_teams": league.total_teams,
                    "status": league.status,
                    "scoring_type": league.scoring_type,
                    "current_week": league.current_week,
                    "last_synced": league.last_synced.isoformat() if league.last_synced else None
                }
                for league in leagues
            ]
        }
    except Exception as e:
        logger.error(f"Error getting user leagues: {e}")
        raise HTTPException(status_code=500, detail="Failed to get leagues")

@router.get("/leagues/{league_id}/standings")
async def get_league_standings(
    league_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get standings for a specific league"""
    try:
        service = FantasyServiceV2(db)
        
        # Verify league ownership
        league = db.query(League).filter(
            League.id == league_id,
            League.user_id == current_user.id
        ).first()
        
        if not league:
            raise HTTPException(status_code=404, detail="League not found")
        
        standings = service.get_league_standings(league_id)
        
        return {
            "success": True,
            "league": {
                "id": league.id,
                "name": league.name,
                "season": league.season,
                "current_week": league.current_week
            },
            "standings": standings
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting league standings: {e}")
        raise HTTPException(status_code=500, detail="Failed to get standings")

@router.get("/teams/{team_id}/analysis")
async def get_team_analysis(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get comprehensive team analysis"""
    try:
        service = FantasyServiceV2(db)
        
        # Verify team access through league ownership
        team = db.query(Team).join(League).filter(
            Team.id == team_id,
            League.user_id == current_user.id
        ).first()
        
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        analysis = service.get_team_analysis(team_id)
        
        return {
            "success": True,
            "team_analysis": analysis
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting team analysis: {e}")
        raise HTTPException(status_code=500, detail="Failed to get team analysis")

@router.get("/teams/by-external-id/{external_team_id}")
async def get_team_by_external_id(
    external_team_id: str,
    league_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get team by external ID (e.g., Sleeper roster ID)"""
    try:
        service = FantasyServiceV2(db)
        
        if league_id:
            # Verify league ownership first
            league = db.query(League).filter(
                League.id == league_id,
                League.user_id == current_user.id
            ).first()
            
            if not league:
                raise HTTPException(status_code=404, detail="League not found")
        
        team = service.get_team_by_external_id(external_team_id, league_id)
        
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        # Double-check ownership through league
        if team.league.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        analysis = service.get_team_analysis(team.id)
        
        return {
            "success": True,
            "team": {
                "id": team.id,
                "external_team_id": team.external_team_id,
                "league_id": team.league_id
            },
            "team_analysis": analysis
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting team by external ID: {e}")
        raise HTTPException(status_code=500, detail="Failed to get team")

@router.get("/players/search")
async def search_players(
    q: str = Query(..., description="Search query"),
    position: Optional[str] = Query(None, description="Filter by position"),
    limit: int = Query(20, le=50, description="Number of results"),
    db: Session = Depends(get_db)
):
    """Search for players"""
    try:
        service = FantasyServiceV2(db)
        players = service.search_players(q, position, limit)
        
        return {
            "success": True,
            "players": [
                {
                    "id": player.id,
                    "sleeper_id": player.sleeper_id,
                    "name": player.display_name,
                    "position": player.position,
                    "nfl_team": player.nfl_team,
                    "trade_value": player.trade_value,
                    "status": player.status,
                    "is_injured": player.is_injured
                }
                for player in players
            ]
        }
    except Exception as e:
        logger.error(f"Error searching players: {e}")
        raise HTTPException(status_code=500, detail="Failed to search players")

@router.get("/players/top/{position}")
async def get_top_players(
    position: str,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db)
):
    """Get top players at a position by trade value"""
    try:
        service = FantasyServiceV2(db)
        players = service.get_top_players_by_position(position, limit)
        
        return {
            "success": True,
            "position": position,
            "players": [
                {
                    "id": player.id,
                    "sleeper_id": player.sleeper_id,
                    "name": player.display_name,
                    "position": player.position,
                    "nfl_team": player.nfl_team,
                    "trade_value": player.trade_value,
                    "status": player.status,
                    "is_injured": player.is_injured
                }
                for player in players
            ]
        }
    except Exception as e:
        logger.error(f"Error getting top players: {e}")
        raise HTTPException(status_code=500, detail="Failed to get top players")

@router.post("/trades/analyze")
async def analyze_trade(
    trade_data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze a potential trade
    
    Expected trade_data format:
    {
        "team1_id": 1,
        "team1_gives": ["player_id_1", "player_id_2"],
        "team1_receives": ["player_id_3"],
        "team2_id": 2,
        "team2_gives": ["player_id_3"],
        "team2_receives": ["player_id_1", "player_id_2"]
    }
    """
    try:
        service = FantasyServiceV2(db)
        
        # Verify team access
        team1 = db.query(service.Team).join(service.League).filter(
            service.Team.id == trade_data["team1_id"],
            League.user_id == current_user.id
        ).first()
        
        team2 = db.query(service.Team).join(service.League).filter(
            service.Team.id == trade_data["team2_id"],
            League.user_id == current_user.id
        ).first()
        
        if not team1 or not team2:
            raise HTTPException(status_code=404, detail="One or both teams not found")
        
        analysis = service.analyze_trade(
            trade_data["team1_id"], trade_data["team1_gives"], trade_data["team1_receives"],
            trade_data["team2_id"], trade_data["team2_gives"], trade_data["team2_receives"]
        )
        
        return {
            "success": True,
            "trade_analysis": analysis
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing trade: {e}")
        raise HTTPException(status_code=500, detail="Failed to analyze trade")

@router.get("/teams/{team_id}/trade-recommendations")
async def get_trade_recommendations(
    team_id: int,
    limit: int = Query(5, le=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get AI-powered trade recommendations for a team"""
    try:
        service = FantasyServiceV2(db)
        
        # Verify team access
        team = db.query(Team).join(League).filter(
            Team.id == team_id,
            League.user_id == current_user.id
        ).first()
        
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        recommendations = service.get_trade_recommendations(team_id, limit)
        
        return {
            "success": True,
            "team_id": team_id,
            "recommendations": recommendations
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trade recommendations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get trade recommendations")

@router.get("/leagues/{league_id}/analytics")
async def get_league_analytics(
    league_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get comprehensive league analytics"""
    try:
        service = FantasyServiceV2(db)
        
        # Verify league ownership
        league = db.query(League).filter(
            League.id == league_id,
            League.user_id == current_user.id
        ).first()
        
        if not league:
            raise HTTPException(status_code=404, detail="League not found")
        
        analytics = service.get_league_analytics(league_id)
        
        return {
            "success": True,
            "analytics": analytics
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting league analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get league analytics")

# SIMPLIFIED ENDPOINTS FOR COMPATIBILITY

@router.get("/simple/standings/{external_league_id}")
async def get_simple_standings(
    external_league_id: str,
    db: Session = Depends(get_db)
):
    """Simplified standings endpoint for compatibility (no auth required for testing)"""
    try:
        service = FantasyServiceV2(db)
        
        # Find league by external ID (any user for simplicity)
        league = db.query(League).filter(
            service.League.external_league_id == external_league_id
        ).first()
        
        if not league:
            raise HTTPException(status_code=404, detail="League not found")
        
        standings = service.get_league_standings(league.id)
        
        return {
            "success": True,
            "league_name": league.name,
            "season": league.season,
            "standings": standings
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting simple standings: {e}")
        raise HTTPException(status_code=500, detail="Failed to get standings")

@router.get("/simple/team-analysis/{external_team_id}")
async def get_simple_team_analysis(
    external_team_id: str,
    db: Session = Depends(get_db)
):
    """Simplified team analysis endpoint for compatibility"""
    try:
        service = FantasyServiceV2(db)
        
        team = service.get_team_by_external_id(external_team_id)
        
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        analysis = service.get_team_analysis(team.id)
        
        # Format for frontend compatibility
        formatted_analysis = {
            "team_info": analysis["team_info"],
            "roster_analysis": {
                "position_strengths": analysis["roster_analysis"]["position_strengths"],
                "position_needs": analysis["roster_analysis"]["position_needs"],
                "surplus_positions": [pos for pos, strength in analysis["roster_analysis"]["position_strengths"].items() if strength > 80]
            },
            "tradeable_assets": {
                "valuable_players": analysis["tradeable_assets"]["valuable_players"],
                "expendable_players": analysis["tradeable_assets"]["expendable_players"],
                "surplus_players": analysis["tradeable_assets"]["surplus_players"],
                "tradeable_picks": []  # Placeholder
            },
            "trade_strategy": {
                "competitive_analysis": {
                    "competitive_tier": "competitive",  # Simplified
                    "team_rank": 1  # Placeholder
                },
                "trade_preferences": [],
                "recommended_approach": "Make targeted upgrades to improve weak positions"
            }
        }
        
        return {
            "success": True,
            "team_analysis": formatted_analysis,
            "league_context": {
                "scoring_type": team.league.scoring_type,
                "current_week": team.league.current_week,
                "trade_deadline_weeks": team.league.trade_deadline_week,
                "playoff_implications": False
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting simple team analysis: {e}")
        raise HTTPException(status_code=500, detail="Failed to get team analysis")