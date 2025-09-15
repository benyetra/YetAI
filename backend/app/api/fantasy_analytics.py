"""
Fantasy Analytics API endpoints - Leverages historical NFL data
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

from app.core.database import get_db
from app.services.fantasy_analytics_service import FantasyAnalyticsService
from app.services.fantasy_service import FantasyService
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models
class PlayerTrendResponse(BaseModel):
    player_name: str
    games_analyzed: int
    trends: Dict[str, Any]
    consistency: Dict[str, Any]
    recent_games: List[Dict[str, Any]]

class MatchupAnalysisResponse(BaseModel):
    player_name: str
    position: Optional[str]
    opponent: str
    week: int
    matchup_rating: str
    matchup_advantage: float
    season_avg_points: float
    vs_opponent_avg: float
    historical_vs_opponent: Dict[str, Any]
    recent_form: Dict[str, Any]

class BreakoutCandidate(BaseModel):
    player_id: int
    player_name: str
    position: str
    team: str
    breakout_score: float
    snap_increase: float
    target_share_increase: float
    recent_avg_points: float
    reasons: List[str]

class RegressionCandidate(BaseModel):
    player_id: int
    player_name: str
    position: str
    team: str
    regression_score: float
    avg_efficiency: float
    expected_efficiency: float
    td_dependent: bool
    risk_level: str
    reasons: List[str]

class ConsistencyRanking(BaseModel):
    player_id: int
    player_name: str
    position: str
    team: str
    consistency_score: float
    avg_points: float
    std_dev: float
    games_analyzed: int
    boom_rate: float
    bust_rate: float
    rating: str

class PlayerProjection(BaseModel):
    player_id: int
    player_name: str
    position: str
    week: int
    projection: float
    floor: float
    ceiling: float
    confidence: float
    trend_adjustment: float
    consistency_rating: str
    scoring_type: str
    factors: Dict[str, Any]

class WaiverAnalytics(BaseModel):
    player_id: int
    player_name: str
    position: str
    team: str
    ownership_pct: float
    opportunity_score: float
    recent_ppg: float
    avg_snap_pct: float
    priority: str
    recommendation: str

class TradeAnalysis(BaseModel):
    players: List[Dict[str, Any]]
    team1_total_value: float
    team2_total_value: float
    fairness_score: float
    trade_grade: str
    recommendation: str

@router.get("/player/{player_id}/trends", response_model=PlayerTrendResponse)
async def get_player_trends(
    player_id: int,
    weeks_back: int = Query(4, ge=1, le=16),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get player trend analysis using historical data"""
    try:
        analytics_service = FantasyAnalyticsService(db)
        trends = analytics_service.get_player_trend_analysis(player_id, weeks_back)

        if "error" in trends:
            raise HTTPException(status_code=404, detail=trends["error"])

        return PlayerTrendResponse(**trends)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting player trends: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/player/{player_id}/matchup", response_model=MatchupAnalysisResponse)
async def get_matchup_analysis(
    player_id: int,
    opponent: str,
    week: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Analyze player matchup using historical data"""
    try:
        analytics_service = FantasyAnalyticsService(db)
        analysis = analytics_service.get_matchup_analysis(player_id, opponent, week)

        if "error" in analysis:
            raise HTTPException(status_code=404, detail=analysis["error"])

        return MatchupAnalysisResponse(**analysis)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing matchup: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/breakout-candidates", response_model=List[BreakoutCandidate])
async def get_breakout_candidates(
    position: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Identify potential breakout players based on usage trends"""
    try:
        analytics_service = FantasyAnalyticsService(db)
        candidates = analytics_service.get_breakout_candidates(position, limit)

        return [BreakoutCandidate(**c) for c in candidates]

    except Exception as e:
        logger.error(f"Error finding breakout candidates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/regression-candidates", response_model=List[RegressionCandidate])
async def get_regression_candidates(
    limit: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Identify players likely to regress based on unsustainable metrics"""
    try:
        analytics_service = FantasyAnalyticsService(db)
        candidates = analytics_service.get_regression_candidates(limit)

        return [RegressionCandidate(**c) for c in candidates]

    except Exception as e:
        logger.error(f"Error finding regression candidates: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/consistency-rankings/{position}", response_model=List[ConsistencyRanking])
async def get_consistency_rankings(
    position: str,
    scoring_type: str = Query("ppr", regex="^(ppr|half_ppr|standard)$"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Rank players by consistency for different scoring formats"""
    try:
        analytics_service = FantasyAnalyticsService(db)
        rankings = analytics_service.get_consistency_rankings(position, scoring_type)

        return [ConsistencyRanking(**r) for r in rankings]

    except Exception as e:
        logger.error(f"Error getting consistency rankings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/player/{player_id}/projection", response_model=PlayerProjection)
async def get_player_projection(
    player_id: int,
    week: int,
    league_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate advanced projection for a player using historical data"""
    try:
        # Get league settings
        fantasy_service = FantasyService(db)
        leagues = fantasy_service.get_user_leagues(current_user["id"])
        league = next((l for l in leagues if l["id"] == league_id), None)

        if not league:
            raise HTTPException(status_code=404, detail="League not found")

        league_settings = {
            "scoring_type": league.get("scoring_type", "ppr"),
            "team_count": league.get("team_count", 12),
            "superflex": False  # Would need to check roster positions
        }

        analytics_service = FantasyAnalyticsService(db)
        projection = analytics_service.get_advanced_player_projection(player_id, week, league_settings)

        if "error" in projection:
            raise HTTPException(status_code=404, detail=projection["error"])

        return PlayerProjection(**projection)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating player projection: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/waiver-analytics", response_model=List[WaiverAnalytics])
async def get_waiver_analytics(
    league_id: int,
    position: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get advanced waiver wire analytics"""
    try:
        analytics_service = FantasyAnalyticsService(db)
        analytics = analytics_service.get_waiver_wire_analytics(league_id, position)

        return [WaiverAnalytics(**a) for a in analytics]

    except Exception as e:
        logger.error(f"Error getting waiver analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trade-analysis", response_model=TradeAnalysis)
async def analyze_trade(
    player_ids: List[int],
    league_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Analyze trade value using historical performance"""
    try:
        # Get league settings
        fantasy_service = FantasyService(db)
        leagues = fantasy_service.get_user_leagues(current_user["id"])
        league = next((l for l in leagues if l["id"] == league_id), None)

        if not league:
            raise HTTPException(status_code=404, detail="League not found")

        league_settings = {
            "scoring_type": league.get("scoring_type", "ppr"),
            "team_count": league.get("team_count", 12),
            "superflex": False
        }

        analytics_service = FantasyAnalyticsService(db)
        analysis = analytics_service.get_trade_value_analysis(player_ids, league_settings)

        if "error" in analysis:
            raise HTTPException(status_code=400, detail=analysis["error"])

        return TradeAnalysis(**analysis)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing trade: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/league/{league_id}/insights")
async def get_league_insights(
    league_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get comprehensive league insights using all available data"""
    try:
        fantasy_service = FantasyService(db)
        analytics_service = FantasyAnalyticsService(db)

        # Verify user has access to league
        leagues = fantasy_service.get_user_leagues(current_user["id"])
        league = next((l for l in leagues if l["id"] == league_id), None)

        if not league:
            raise HTTPException(status_code=404, detail="League not found")

        # Get various analytics
        breakout_candidates = analytics_service.get_breakout_candidates(limit=5)
        regression_candidates = analytics_service.get_regression_candidates(limit=5)

        # Get position-specific consistency rankings
        rb_consistency = analytics_service.get_consistency_rankings("RB", league.get("scoring_type", "ppr"))[:5]
        wr_consistency = analytics_service.get_consistency_rankings("WR", league.get("scoring_type", "ppr"))[:5]

        return {
            "league_name": league["name"],
            "scoring_type": league.get("scoring_type", "ppr"),
            "insights": {
                "breakout_watch": breakout_candidates,
                "regression_alerts": regression_candidates,
                "consistency_leaders": {
                    "RB": rb_consistency,
                    "WR": wr_consistency
                },
                "key_trends": [
                    "Players with rising snap counts and target shares",
                    "TD regression candidates identified",
                    "Consistency ratings updated with 4 seasons of data"
                ]
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting league insights: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/data-summary")
async def get_data_summary(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get summary of available historical data"""
    try:
        from app.models.fantasy_models import PlayerAnalytics
        from sqlalchemy import func

        # Get data coverage summary
        coverage = db.query(
            PlayerAnalytics.season,
            func.count(func.distinct(PlayerAnalytics.player_id)).label('unique_players'),
            func.count(func.distinct(PlayerAnalytics.week)).label('weeks'),
            func.count(PlayerAnalytics.id).label('total_records')
        ).group_by(PlayerAnalytics.season).order_by(PlayerAnalytics.season).all()

        total_records = db.query(func.count(PlayerAnalytics.id)).scalar()
        unique_players = db.query(func.count(func.distinct(PlayerAnalytics.player_id))).scalar()

        return {
            "summary": {
                "total_records": total_records,
                "unique_players": unique_players,
                "seasons_covered": [c[0] for c in coverage],
                "data_points": [
                    "Snap counts", "Target shares", "Red zone usage",
                    "Air yards", "Route participation", "Efficiency metrics",
                    "Consistency scores", "Boom/bust rates"
                ]
            },
            "coverage_by_season": [
                {
                    "season": c[0],
                    "players": c[1],
                    "weeks": c[2],
                    "records": c[3]
                }
                for c in coverage
            ],
            "analytics_available": [
                "Player trend analysis",
                "Matchup analysis",
                "Breakout candidate identification",
                "Regression analysis",
                "Consistency rankings",
                "Advanced projections",
                "Trade value analysis",
                "Waiver wire analytics"
            ]
        }

    except Exception as e:
        logger.error(f"Error getting data summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))