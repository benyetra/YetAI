"""
Advanced Analytics API - Performance vs Expectation, Trade Values, Team Analysis
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime
import logging

from app.core.database import get_db
from app.services.advanced_analytics_service import AdvancedAnalyticsService
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models
class PvEResponse(BaseModel):
    player_id: int
    player_name: str
    position: str
    pve_score: float
    category: str
    trend: str
    current_season: Dict[str, Any]
    historical_baseline: Dict[str, Any]
    usage_changes: Dict[str, float]
    statistical_significance: Dict[str, Any]
    recommendation: str

class TradeValueResponse(BaseModel):
    player_id: int
    player_name: str
    position: str
    trade_value: float
    tier: str
    recommended_action: str
    value_factors: Dict[str, Any]
    comparable_players: List[Dict]

class TeamAnalysisResponse(BaseModel):
    team_id: int
    team_name: str
    overall_rating: str
    avg_pve_score: float
    roster_analysis: List[Dict]
    position_groups: Dict[str, Any]
    strengths: List[Dict]
    weaknesses: List[Dict]
    recommendations: List[Dict]
    championship_probability: float

class PlayerComparisonResponse(BaseModel):
    players: List[Dict]
    best_value: Optional[Dict]
    insights: List[str]
    trade_recommendations: List[str]

@router.get("/player/{player_id}/pve", response_model=PvEResponse)
async def get_performance_vs_expectation(
    player_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get Performance vs Expectation analysis for a player
    Compares 2025 performance to 2021-2024 baseline
    """
    try:
        service = AdvancedAnalyticsService(db)
        result = service.get_performance_vs_expectation(player_id)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting PvE: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/player/{player_id}/trade-value", response_model=TradeValueResponse)
async def get_trade_value(
    player_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate dynamic trade value based on current performance and historical data
    """
    try:
        service = AdvancedAnalyticsService(db)
        result = service.calculate_dynamic_trade_value(player_id)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return result
        
    except Exception as e:
        logger.error(f"Error calculating trade value: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/team/{team_id}/analysis", response_model=TeamAnalysisResponse)
async def get_team_analysis(
    team_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Comprehensive team construction analysis using 2025 performance data
    """
    try:
        service = AdvancedAnalyticsService(db)
        result = service.get_team_construction_analysis(team_id)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing team: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/players/compare", response_model=PlayerComparisonResponse)
async def compare_players(
    player_ids: List[int],
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Advanced player comparison using 2025 data vs historical baselines
    """
    try:
        if len(player_ids) < 2:
            raise HTTPException(status_code=400, detail="At least 2 players required for comparison")
        
        if len(player_ids) > 5:
            raise HTTPException(status_code=400, detail="Maximum 5 players for comparison")
        
        service = AdvancedAnalyticsService(db)
        result = service.get_player_comparison(player_ids)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return result
        
    except Exception as e:
        logger.error(f"Error comparing players: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/market/movers")
async def get_market_movers(
    limit: int = Query(10, le=20),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get biggest risers and fallers based on PvE scores
    """
    try:
        service = AdvancedAnalyticsService(db)
        
        # Get all players with 2025 data
        from app.models.fantasy_models import PlayerAnalytics, FantasyPlayer
        
        players_with_data = db.query(PlayerAnalytics.player_id).filter(
            PlayerAnalytics.season == 2025
        ).group_by(PlayerAnalytics.player_id).having(
            func.count(PlayerAnalytics.id) >= 3
        ).all()
        
        movers = []
        for player_id in players_with_data[:50]:  # Check top 50 for efficiency
            pve = service.get_performance_vs_expectation(player_id[0])
            if "error" not in pve:
                movers.append({
                    "player_id": player_id[0],
                    "player_name": pve['player_name'],
                    "position": pve['position'],
                    "pve_score": pve['pve_score'],
                    "trend": pve['trend'],
                    "category": pve['category']
                })
        
        # Sort by PvE score
        movers.sort(key=lambda x: abs(x['pve_score'] - 50), reverse=True)
        
        risers = [m for m in movers if m['pve_score'] > 55][:limit]
        fallers = [m for m in movers if m['pve_score'] < 45][:limit]
        
        return {
            "risers": risers,
            "fallers": fallers,
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting market movers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trade-finder")
async def find_trade_targets(
    position: Optional[str] = None,
    min_value: float = Query(0, ge=0, le=100),
    max_value: float = Query(100, ge=0, le=100),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Find trade targets based on value mismatches
    """
    try:
        service = AdvancedAnalyticsService(db)
        from app.models.fantasy_models import FantasyPlayer, PlayerAnalytics
        
        # Get players with 2025 data
        query = db.query(FantasyPlayer).join(PlayerAnalytics).filter(
            PlayerAnalytics.season == 2025
        )
        
        if position:
            query = query.filter(FantasyPlayer.position == position)
        
        players = query.group_by(FantasyPlayer.id).having(
            func.count(PlayerAnalytics.id) >= 2
        ).limit(30).all()
        
        trade_targets = []
        for player in players:
            trade_value = service.calculate_dynamic_trade_value(player.id)
            if "error" not in trade_value:
                if min_value <= trade_value['trade_value'] <= max_value:
                    pve = service.get_performance_vs_expectation(player.id)
                    
                    # Find value mismatches
                    if pve['pve_score'] > 60 and trade_value['trade_value'] < 65:
                        opportunity = "BUY_LOW"
                    elif pve['pve_score'] < 40 and trade_value['trade_value'] > 55:
                        opportunity = "SELL_HIGH"
                    else:
                        opportunity = "FAIR_VALUE"
                    
                    trade_targets.append({
                        "player_id": player.id,
                        "player_name": player.name,
                        "position": player.position,
                        "team": player.team,
                        "trade_value": trade_value['trade_value'],
                        "pve_score": pve['pve_score'],
                        "opportunity": opportunity,
                        "action": trade_value['recommended_action']
                    })
        
        # Sort by opportunity
        buy_targets = [t for t in trade_targets if t['opportunity'] == "BUY_LOW"]
        sell_targets = [t for t in trade_targets if t['opportunity'] == "SELL_HIGH"]
        
        return {
            "buy_low_targets": buy_targets,
            "sell_high_targets": sell_targets,
            "total_analyzed": len(trade_targets)
        }
        
    except Exception as e:
        logger.error(f"Error finding trade targets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))