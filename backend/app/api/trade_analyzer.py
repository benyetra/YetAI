"""
Trade Analyzer API - REST endpoints for fantasy trade analysis and recommendations
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from app.core.database import get_db
from app.services.trade_analyzer_service import TradeAnalyzerService
from app.services.trade_recommendation_engine import TradeRecommendationEngine
from app.models.fantasy_models import Trade, TradeEvaluation, FantasyTeam
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fantasy/trade-analyzer", tags=["Trade Analyzer"])

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class TradeProposalRequest(BaseModel):
    league_id: int
    proposing_team_id: int
    target_team_id: int
    team1_gives: Dict[str, Any]  # {"players": [ids], "picks": [ids], "faab": amount}
    team2_gives: Dict[str, Any]
    trade_reason: Optional[str] = None
    expires_in_hours: Optional[int] = 72

class TradeEvaluationResponse(BaseModel):
    success: bool
    evaluation_id: Optional[int] = None
    trade_id: Optional[int] = None
    grades: Optional[Dict[str, str]] = None
    values: Optional[Dict[str, float]] = None
    analysis: Optional[Dict[str, Any]] = None
    fairness_score: Optional[float] = None
    ai_summary: Optional[str] = None
    key_factors: Optional[List[Dict[str, Any]]] = None
    confidence: Optional[float] = None
    error: Optional[str] = None

class TradeRecommendationRequest(BaseModel):
    team_id: int
    league_id: int
    recommendation_type: Optional[str] = "all"  # "all", "position_need", "buy_low", "sell_high", etc.
    max_recommendations: Optional[int] = 10

class MutualBenefitRequest(BaseModel):
    team_id: int
    league_id: int
    target_team_id: Optional[int] = None

# ============================================================================
# TRADE PROPOSAL AND EVALUATION ENDPOINTS
# ============================================================================

@router.post("/propose-trade", response_model=TradeEvaluationResponse)
async def propose_trade(
    request: TradeProposalRequest,
    db: Session = Depends(get_db)
):
    """Create a new trade proposal with immediate AI evaluation"""
    try:
        trade_analyzer = TradeAnalyzerService(db)
        
        result = trade_analyzer.propose_trade(
            league_id=request.league_id,
            proposing_team_id=request.proposing_team_id,
            target_team_id=request.target_team_id,
            team1_gives=request.team1_gives,
            team2_gives=request.team2_gives,
            trade_reason=request.trade_reason,
            expires_in_hours=request.expires_in_hours
        )
        
        if result["success"]:
            return TradeEvaluationResponse(
                success=True,
                trade_id=result["trade_id"],
                evaluation_id=result["evaluation"]["evaluation_id"],
                grades=result["evaluation"]["grades"],
                values=result["evaluation"]["values"],
                analysis=result["evaluation"]["analysis"],
                fairness_score=result["evaluation"]["fairness_score"],
                ai_summary=result["evaluation"]["ai_summary"],
                key_factors=result["evaluation"]["key_factors"],
                confidence=result["evaluation"]["confidence"]
            )
        else:
            return TradeEvaluationResponse(success=False, error=result["error"])
            
    except Exception as e:
        logger.error(f"Failed to propose trade: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to propose trade"
        )

@router.get("/evaluate-trade/{trade_id}", response_model=TradeEvaluationResponse)
async def evaluate_trade(
    trade_id: int,
    force_refresh: bool = Query(False, description="Force re-evaluation even if cached"),
    db: Session = Depends(get_db)
):
    """Get comprehensive AI evaluation of an existing trade"""
    try:
        trade_analyzer = TradeAnalyzerService(db)
        
        # Verify trade exists
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trade not found"
            )
        
        result = trade_analyzer.evaluate_trade(trade_id, force_refresh=force_refresh)
        
        if result["success"]:
            return TradeEvaluationResponse(
                success=True,
                evaluation_id=result["evaluation_id"],
                trade_id=result["trade_id"],
                grades=result["grades"],
                values=result["values"],
                analysis=result["analysis"],
                fairness_score=result["fairness_score"],
                ai_summary=result["ai_summary"],
                key_factors=result["key_factors"],
                confidence=result["confidence"]
            )
        else:
            return TradeEvaluationResponse(success=False, error=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to evaluate trade {trade_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to evaluate trade"
        )

@router.get("/trade-history/{team_id}")
async def get_team_trade_history(
    team_id: int,
    league_id: int = Query(..., description="League ID"),
    limit: int = Query(20, description="Maximum number of trades to return"),
    db: Session = Depends(get_db)
):
    """Get trade history for a team"""
    try:
        # Verify team exists in league
        team = db.query(FantasyTeam).filter(
            FantasyTeam.id == team_id,
            FantasyTeam.league_id == league_id
        ).first()
        
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found in league"
            )
        
        # Get trades involving this team
        trades = db.query(Trade).filter(
            Trade.league_id == league_id,
            (Trade.team1_id == team_id) | (Trade.team2_id == team_id)
        ).order_by(Trade.created_at.desc()).limit(limit).all()
        
        trade_history = []
        for trade in trades:
            # Get evaluation if exists
            evaluation = db.query(TradeEvaluation).filter(
                TradeEvaluation.trade_id == trade.id
            ).first()
            
            trade_data = {
                "trade_id": trade.id,
                "status": trade.status.value,
                "proposed_at": trade.proposed_at.isoformat(),
                "processed_at": trade.processed_at.isoformat() if trade.processed_at else None,
                "team1_id": trade.team1_id,
                "team2_id": trade.target_team_id,
                "team1_gives": trade.team1_gives,
                "team2_gives": trade.team2_gives,
                "trade_reason": trade.trade_reason,
                "evaluation": {
                    "team1_grade": evaluation.team1_grade.value if evaluation else None,
                    "team2_grade": evaluation.team2_grade.value if evaluation else None,
                    "fairness_score": evaluation.fairness_score if evaluation else None,
                    "ai_summary": evaluation.ai_summary if evaluation else None
                } if evaluation else None
            }
            trade_history.append(trade_data)
        
        return {
            "success": True,
            "team_id": team_id,
            "trade_count": len(trade_history),
            "trades": trade_history
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trade history for team {team_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get trade history"
        )

# ============================================================================
# TRADE RECOMMENDATION ENDPOINTS
# ============================================================================

@router.post("/recommendations")
async def generate_trade_recommendations(
    request: TradeRecommendationRequest,
    db: Session = Depends(get_db)
):
    """Generate AI-powered trade recommendations for a team"""
    try:
        # Verify team exists in league
        team = db.query(FantasyTeam).filter(
            FantasyTeam.id == request.team_id,
            FantasyTeam.league_id == request.league_id
        ).first()
        
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found in league"
            )
        
        recommendation_engine = TradeRecommendationEngine(db)
        
        recommendations = recommendation_engine.generate_trade_recommendations(
            team_id=request.team_id,
            league_id=request.league_id,
            recommendation_type=request.recommendation_type,
            max_recommendations=request.max_recommendations
        )
        
        return {
            "success": True,
            "team_id": request.team_id,
            "league_id": request.league_id,
            "recommendation_type": request.recommendation_type,
            "recommendation_count": len(recommendations),
            "recommendations": recommendations
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate recommendations for team {request.team_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate trade recommendations"
        )

@router.post("/mutual-benefit-trades")
async def find_mutual_benefit_trades(
    request: MutualBenefitRequest,
    db: Session = Depends(get_db)
):
    """Find trades that benefit both teams involved"""
    try:
        # Verify team exists
        team = db.query(FantasyTeam).filter(
            FantasyTeam.id == request.team_id,
            FantasyTeam.league_id == request.league_id
        ).first()
        
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found in league"
            )
        
        # Verify target team if specified
        if request.target_team_id:
            target_team = db.query(FantasyTeam).filter(
                FantasyTeam.id == request.target_team_id,
                FantasyTeam.league_id == request.league_id
            ).first()
            
            if not target_team:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target team not found in league"
                )
        
        recommendation_engine = TradeRecommendationEngine(db)
        
        mutual_trades = recommendation_engine.find_mutual_benefit_trades(
            team_id=request.team_id,
            league_id=request.league_id,
            target_team_id=request.target_team_id
        )
        
        return {
            "success": True,
            "team_id": request.team_id,
            "league_id": request.league_id,
            "target_team_id": request.target_team_id,
            "mutual_benefit_trades": mutual_trades,
            "trade_count": len(mutual_trades)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find mutual benefit trades: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to find mutual benefit trades"
        )

@router.get("/team-analysis/{team_id}")
async def get_team_trade_analysis(
    team_id: int,
    league_id: int = Query(..., description="League ID"),
    db: Session = Depends(get_db)
):
    """Get comprehensive team analysis for trade purposes"""
    try:
        # Verify team exists - get team first, then use its actual league
        team = db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
        
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found"
            )
        
        # Use the team's actual league_id instead of the provided one
        actual_league_id = team.league_id
        
        recommendation_engine = TradeRecommendationEngine(db)
        
        # Get comprehensive team context using the team's actual league
        team_context = recommendation_engine._get_comprehensive_team_context(team_id, actual_league_id)
        league_context = recommendation_engine._get_league_context(actual_league_id)
        
        return {
            "success": True,
            "team_analysis": {
                "team_info": {
                    "team_id": team_context["team_id"],
                    "team_name": team_context["team_name"],
                    "record": team_context["record"],
                    "points_for": team_context["points_for"],
                    "team_rank": team_context["competitive_analysis"]["team_rank"],
                    "competitive_tier": team_context["competitive_analysis"]["competitive_tier"]
                },
                "roster_analysis": {
                    "position_strengths": team_context["position_strength"],
                    "position_needs": team_context["position_needs"],
                    "surplus_positions": team_context["surplus_positions"]
                },
                "tradeable_assets": {
                    "surplus_players": team_context["tradeable_players"]["surplus"],
                    "expendable_players": team_context["tradeable_players"]["expendable"],
                    "valuable_players": team_context["tradeable_players"]["valuable"],
                    "tradeable_picks": team_context["tradeable_picks"]
                },
                "trade_strategy": {
                    "competitive_analysis": team_context["competitive_analysis"],
                    "trade_preferences": team_context["trade_preferences"],
                    "recommended_approach": _get_recommended_approach(team_context)
                }
            },
            "league_context": {
                "scoring_type": league_context["scoring_type"],
                "current_week": league_context["current_week"],
                "trade_deadline_weeks": league_context["trade_deadline_weeks"],
                "playoff_implications": league_context["current_week"] >= 10
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get team analysis for {team_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get team analysis"
        )

def _get_recommended_approach(team_context: Dict[str, Any]) -> str:
    """Get recommended trading approach for team"""
    tier = team_context["competitive_analysis"]["competitive_tier"]
    
    if tier == "championship":
        return "Consolidate talent for playoff push. Trade depth for star players."
    elif tier == "competitive":
        return "Make targeted upgrades without sacrificing future. Focus on position needs."
    elif tier == "bubble":
        return "Cautious improvements. Don't mortgage future for marginal gains."
    else:
        return "Rebuild mode. Sell aging players for youth and draft picks."

# ============================================================================
# QUICK TRADE ANALYSIS ENDPOINTS
# ============================================================================

@router.post("/quick-analysis")
async def quick_trade_analysis(
    trade_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Quick trade analysis without storing in database"""
    try:
        # Validate required fields
        required_fields = ["league_id", "team1_id", "team2_id", "team1_gives", "team2_gives"]
        for field in required_fields:
            if field not in trade_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required field: {field}"
                )
        
        trade_analyzer = TradeAnalyzerService(db)
        
        # Create temporary trade object for analysis
        from app.models.fantasy_models import Trade
        temp_trade = Trade(
            league_id=trade_data["league_id"],
            team1_id=trade_data["team1_id"],
            team2_id=trade_data["team2_id"],
            team1_gives=trade_data["team1_gives"],
            team2_gives=trade_data["team2_gives"],
            proposed_by_team_id=trade_data["team1_id"],
            status="proposed"
        )
        
        # Generate evaluation without storing
        evaluation_data = trade_analyzer._generate_comprehensive_evaluation(temp_trade)
        
        return {
            "success": True,
            "quick_analysis": {
                "team1_grade": evaluation_data["team1_grade"].value,
                "team2_grade": evaluation_data["team2_grade"].value,
                "fairness_score": evaluation_data["fairness_score"],
                "ai_summary": evaluation_data["ai_summary"],
                "key_factors": evaluation_data["key_factors"][:3],  # Top 3 factors
                "confidence": evaluation_data["confidence"]
            },
            "value_breakdown": {
                "team1_value_given": evaluation_data["team1_value_given"],
                "team1_value_received": evaluation_data["team1_value_received"],
                "team2_value_given": evaluation_data["team2_value_given"],
                "team2_value_received": evaluation_data["team2_value_received"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to perform quick trade analysis: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to perform quick trade analysis"
        )

@router.get("/player-values/{league_id}")
async def get_league_player_values(
    league_id: int,
    position: Optional[str] = Query(None, description="Filter by position"),
    limit: int = Query(50, description="Maximum players to return"),
    db: Session = Depends(get_db)
):
    """Get current player values for trade analysis"""
    try:
        from app.models.fantasy_models import PlayerValue, FantasyPlayer
        
        # Build query
        query = db.query(PlayerValue, FantasyPlayer).join(
            FantasyPlayer, PlayerValue.player_id == FantasyPlayer.id
        ).filter(PlayerValue.league_id == league_id)
        
        if position:
            query = query.filter(FantasyPlayer.position == position.upper())
        
        # Get latest values per player
        player_values = query.order_by(
            PlayerValue.player_id,
            PlayerValue.week.desc()
        ).limit(limit).all()
        
        # Format response
        values_data = []
        for player_value, player in player_values:
            values_data.append({
                "player_id": player.id,
                "player_name": player.name,
                "position": player.position,
                "team": player.team,
                "rest_of_season_value": player_value.rest_of_season_value,
                "ppr_value": player_value.ppr_value,
                "standard_value": player_value.standard_value,
                "dynasty_value": player_value.dynasty_value,
                "last_updated": player_value.created_at.isoformat()
            })
        
        return {
            "success": True,
            "league_id": league_id,
            "position_filter": position,
            "player_count": len(values_data),
            "player_values": values_data
        }
        
    except Exception as e:
        logger.error(f"Failed to get player values for league {league_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get player values"
        )