from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio
import logging
from datetime import datetime

from app.services.data_pipeline import sports_pipeline
from app.services.fantasy_pipeline import fantasy_pipeline
from app.services.ai_chat_service import ai_chat_service
from app.services.real_fantasy_pipeline import real_fantasy_pipeline
from app.services.performance_tracker import performance_tracker
from app.services.auth_service_db import auth_service_db as auth_service
from app.services.avatar_service import avatar_service
from app.services.bet_service_db import bet_service_db as bet_service
from app.services.yetai_bets_service_db import yetai_bets_service_db as yetai_bets_service
from app.services.live_betting_service_db import live_betting_service_db as live_betting_service
from app.services.live_betting_simulator import live_betting_simulator
from app.services.bet_sharing_service_db import bet_sharing_service_db as bet_sharing_service
from app.services.websocket_manager import manager, simulate_odds_updates, simulate_score_updates
from app.services.odds_api_service import OddsAPIService, SportKey, MarketKey, OddsFormat
from app.services.cache_service import cache_service
from app.services.scheduler_service import scheduler_service
from app.services.google_oauth_service import google_oauth_service
from app.services.betting_analytics_service import betting_analytics_service
from app.services.bet_verification_service import bet_verification_service
from app.services.bet_scheduler_service import bet_scheduler, init_scheduler, cleanup_scheduler
from app.services.fantasy_service import FantasyService
from app.services.sleeper_fantasy_service import SleeperFantasyService
from app.models.bet_models import *
from app.models.live_bet_models import *
from app.models.fantasy_models import FantasyPlatform
from app.core.config import settings
from app.core.database import init_db, check_db_connection
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chat Models
class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None

# Security scheme
security = HTTPBearer()

# Auth Request/Response models
class UserSignup(BaseModel):
    email: EmailStr
    username: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class UserLogin(BaseModel):
    email_or_username: str
    password: str

class UserPreferences(BaseModel):
    favorite_teams: Optional[list] = None
    preferred_sports: Optional[list] = None
    notification_settings: Optional[dict] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None

class SubscriptionUpgrade(BaseModel):
    tier: str  # "pro" or "elite"

# 2FA Request models
class Setup2FARequest(BaseModel):
    pass  # No additional data needed

class Enable2FARequest(BaseModel):
    token: str = Field(min_length=6, max_length=6)

class Disable2FARequest(BaseModel):
    password: str
    token: str  # Can be TOTP token or backup code

class Verify2FARequest(BaseModel):
    token: str

app = FastAPI(
    title="AI Sports Betting MVP",
    description="AI-powered sports betting and fantasy insights platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Mount static files for avatars
app.mount("/uploads", StaticFiles(directory="app/uploads"), name="uploads")

# CORS middleware - MUST be configured properly for OPTIONS requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://192.168.1.44:3000",
        "http://192.168.1.44:3001",
        "ws://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)

# Handle OPTIONS requests explicitly
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
        }
    )

# Dependency to get current user
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    token = credentials.credentials
    user = await auth_service.get_user_by_token(token)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# Optional user dependency (doesn't require auth)
async def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))):
    """Get current user if authenticated, None otherwise"""
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        user = await auth_service.get_user_by_token(token)
        return user
    except:
        return None

@app.get("/")
async def root():
    return {
        "message": "AI Sports Betting MVP API",
        "version": "0.1.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Test endpoints for development
@app.get("/test/odds")
async def test_odds():
    # Mock odds data for testing
    return {
        "game": "Team A vs Team B",
        "odds": {
            "moneyline": {"home": -110, "away": +120},
            "spread": {"line": -3.5, "odds": -110}
        },
        "recommendation": "Value bet on away team moneyline"
    }

@app.get("/test/fantasy")
async def test_fantasy():
    # Mock fantasy data
    return {
        "player": "John Doe",
        "position": "QB",
        "projected_points": 24.5,
        "recommendation": "Strong start this week"
    }

# Real API endpoints
@app.get("/api/games/nfl")
async def get_nfl_games():
    """Get current NFL games"""
    try:
        games = await sports_pipeline.get_nfl_games_today()
        return {
            "status": "success",
            "count": len(games),
            "games": games
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching games: {str(e)}")

@app.get("/api/odds/nfl")
async def get_nfl_odds():
    """Get current NFL betting odds"""
    try:
        odds = await sports_pipeline.get_nfl_odds()
        return {
            "status": "success",
            "count": len(odds),
            "odds": odds
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching odds: {str(e)}")

@app.get("/api/predictions/daily")
async def get_daily_predictions():
    """Get today's AI betting predictions"""
    try:
        # Fetch both games and odds
        games_task = sports_pipeline.get_nfl_games_today()
        odds_task = sports_pipeline.get_nfl_odds()
        
        games, odds = await asyncio.gather(games_task, odds_task)
        
        # Generate predictions
        predictions = sports_pipeline.generate_simple_predictions(games, odds)
        
        return {
            "status": "success",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(predictions),
            "predictions": predictions,
            "disclaimer": "For entertainment purposes only. Bet responsibly."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating predictions: {str(e)}")

@app.get("/api/data/status")
async def get_data_status():
    """Check status of all data sources"""
    status = {
        "espn_api": "unknown",
        "odds_api": "unknown",
        "last_updated": None
    }
    
    try:
        # Test ESPN API
        games = await sports_pipeline.get_nfl_games_today()
        status["espn_api"] = "connected" if games else "no_data"
        
        # Test Odds API
        odds = await sports_pipeline.get_nfl_odds()
        status["odds_api"] = "connected" if odds else "no_key_or_error"
        
        status["last_updated"] = datetime.now().isoformat()
        
    except Exception as e:
        status["error"] = str(e)
    
    return status

# Fantasy API endpoints
@app.get("/api/fantasy/projections")
async def get_fantasy_projections():
    """Get weekly fantasy point projections for all players"""
    try:
        players_task = fantasy_pipeline.get_nfl_players(limit=100)
        games_task = sports_pipeline.get_nfl_games_today()
        
        players, games = await asyncio.gather(players_task, games_task)
        projections = fantasy_pipeline.generate_fantasy_projections(players, games)
        
        return {
            "status": "success",
            "week": "Current Week",
            "count": len(projections),
            "projections": projections,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating projections: {str(e)}")

@app.get("/api/fantasy/start-sit/{position}")
async def get_start_sit_advice(position: str):
    """Get start/sit advice for specific position"""
    try:
        valid_positions = ['QB', 'RB', 'WR', 'TE', 'K']
        if position.upper() not in valid_positions:
            raise HTTPException(status_code=400, detail=f"Invalid position. Must be one of: {valid_positions}")
        
        players = await fantasy_pipeline.get_nfl_players(limit=200)
        games = await sports_pipeline.get_nfl_games_today()
        projections = fantasy_pipeline.generate_fantasy_projections(players, games)
        advice = fantasy_pipeline.get_start_sit_advice(projections, position.upper())
        
        return {
            "status": "success",
            "position": position.upper(),
            "count": len(advice),
            "advice": advice,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting start/sit advice: {str(e)}")

# AI Chat endpoints
@app.post("/api/chat/message")
async def send_chat_message(request: ChatRequest):
    """Send a message to the AI chat assistant"""
    try:
        history = []
        if request.conversation_history:
            for msg in request.conversation_history:
                history.append({"role": msg.role, "content": msg.content})
        
        response = await ai_chat_service.get_chat_response(request.message, history)
        
        return {
            "status": "success",
            "message": response["response"],
            "type": response["type"],
            "timestamp": response.get("timestamp"),
            "context_used": response.get("context_used", {}),
            "disclaimer": "For entertainment purposes only. Please bet responsibly."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat message: {str(e)}")

@app.get("/api/chat/suggestions")
async def get_chat_suggestions():
    """Get quick suggestion prompts for the chat"""
    try:
        suggestions = await ai_chat_service.get_quick_suggestions()
        return {"status": "success", "suggestions": suggestions, "count": len(suggestions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting suggestions: {str(e)}")

@app.get("/api/chat/health")
async def check_chat_health():
    """Check if AI chat services are working"""
    health_status = {
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "data_sources": {"games_api": False, "odds_api": False, "fantasy_api": False},
        "status": "unknown"
    }
    
    try:
        context_data = await ai_chat_service.get_context_data()
        health_status["data_sources"]["games_api"] = len(context_data.get("games", [])) > 0
        health_status["data_sources"]["odds_api"] = len(context_data.get("odds", [])) > 0
        health_status["data_sources"]["fantasy_api"] = len(context_data.get("fantasy_projections", [])) > 0
        
        if health_status["openai_configured"] and any(health_status["data_sources"].values()):
            health_status["status"] = "healthy"
        elif health_status["openai_configured"]:
            health_status["status"] = "limited"
        else:
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["status"] = "error"
        health_status["error"] = str(e)
    
    return health_status

# Enhanced Fantasy API endpoints
@app.get("/api/fantasy/projections/v2")
async def get_enhanced_fantasy_projections():
    """Get enhanced fantasy projections using real player stats"""
    try:
        # Get real player stats
        logger.info("Fetching real player season stats...")
        player_stats = await real_fantasy_pipeline.get_player_season_stats()
        
        # Get games for context
        games = await sports_pipeline.get_nfl_games_today()
        
        # Get injury reports
        injury_data = await real_fantasy_pipeline.get_injury_reports()
        
        # Get weather data
        weather_data = await real_fantasy_pipeline.get_weather_data(games)
        
        # Generate advanced projections
        projections = real_fantasy_pipeline.calculate_advanced_projections(
            player_stats, games, injury_data, weather_data
        )
        
        # Record predictions for tracking (async)
        for projection in projections[:10]:  # Track top 10 projections
            asyncio.create_task(performance_tracker.record_prediction({
                'type': 'fantasy',
                'player_id': projection['player_id'],
                'name': projection['name'],
                'team': projection['team'],
                'position': projection['position'],
                'opponent': projection['opponent'],
                'predicted_points': projection['projected_points'],
                'confidence': projection['confidence'],
                'reasoning': projection['reasoning'],
                'game_date': projection['game_date']
            }))
        
        return {
            "status": "success",
            "version": "2.0",
            "data_sources": {
                "player_stats": len(player_stats),
                "injury_reports": len(injury_data),
                "weather_data": len(weather_data),
                "games": len(games)
            },
            "projections": projections,
            "last_updated": datetime.now().isoformat(),
            "methodology": "Real season stats + injury reports + weather + matchup analysis"
        }
        
    except Exception as e:
        logger.error(f"Error generating enhanced projections: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating projections: {str(e)}")

@app.get("/api/fantasy/player-stats/{player_id}")
async def get_detailed_player_stats(player_id: str):
    """Get detailed season stats for a specific player"""
    try:
        # Get all player stats
        all_stats = await real_fantasy_pipeline.get_player_season_stats()
        
        if player_id not in all_stats:
            raise HTTPException(status_code=404, detail="Player not found")
        
        player_data = all_stats[player_id]
        
        # Calculate per-game averages
        games_played = player_data['stats'].get('games_played', 1)
        per_game_stats = {}
        
        for stat_name, value in player_data['stats'].items():
            if stat_name != 'games_played' and isinstance(value, (int, float)):
                per_game_stats[f"{stat_name}_per_game"] = round(value / games_played, 2)
        
        return {
            "status": "success",
            "player": {
                "id": player_id,
                "name": player_data['name'],
                "position": player_data['position'],
                "team": player_data['team'],
                "age": player_data.get('age'),
                "season_stats": player_data['stats'],
                "per_game_averages": per_game_stats,
                "games_played": games_played
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching player stats: {str(e)}")

@app.get("/api/performance/metrics")
async def get_prediction_performance():
    """Get prediction accuracy and performance metrics"""
    try:
        metrics = await performance_tracker.get_performance_metrics(days=30)
        return {
            "status": "success",
            "metrics": metrics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching performance metrics: {str(e)}")

@app.get("/api/performance/best-predictions")
async def get_best_predictions():
    """Get the most accurate recent predictions"""
    try:
        best_preds = await performance_tracker.get_best_predictions(limit=15)
        return {
            "status": "success",
            "best_predictions": best_preds,
            "count": len(best_preds)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching best predictions: {str(e)}")

@app.post("/api/performance/simulate-data")
async def simulate_historical_performance():
    """Generate sample historical performance data for demo"""
    try:
        await performance_tracker.simulate_historical_data()
        return {
            "status": "success", 
            "message": "Sample historical data generated"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating sample data: {str(e)}")

@app.get("/api/fantasy/injury-report")
async def get_current_injury_report():
    """Get current injury reports for fantasy-relevant players"""
    try:
        injury_data = await real_fantasy_pipeline.get_injury_reports()
        
        # Format for frontend
        formatted_injuries = []
        for player_key, status in injury_data.items():
            formatted_injuries.append({
                "player": player_key.replace('_', ' ').title(),
                "status": status,
                "severity": "high" if status == "out" else "medium" if status in ["doubtful", "questionable"] else "low"
            })
        
        return {
            "status": "success",
            "injury_report": formatted_injuries,
            "last_updated": datetime.now().isoformat(),
            "total_players": len(formatted_injuries)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching injury report: {str(e)}")

@app.get("/api/fantasy/weather-impact")
async def get_weather_impact():
    """Get weather impact analysis for upcoming games"""
    try:
        games = await sports_pipeline.get_nfl_games_today()
        weather_data = await real_fantasy_pipeline.get_weather_data(games)
        
        # Format weather impact
        weather_impact = []
        for game_key, weather in weather_data.items():
            teams = game_key.split('_vs_')
            weather_impact.append({
                "matchup": f"{teams[0]} vs {teams[1]}",
                "conditions": weather['conditions'],
                "temperature": weather['temperature'],
                "wind_speed": weather['wind_speed'],
                "impact_rating": weather['impact_rating'],
                "fantasy_advice": {
                    "passing": "reduced" if weather['impact_rating'] == "high" else "normal",
                    "kicking": "difficult" if weather['wind_speed'] > 15 else "normal",
                    "running": "enhanced" if weather['impact_rating'] == "high" else "normal"
                }
            })
        
        return {
            "status": "success",
            "weather_impact": weather_impact,
            "games_analyzed": len(weather_impact)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching weather impact: {str(e)}")

# Fantasy League Integration Endpoints
from app.core.database import get_db

# Global fantasy service instance
fantasy_service_instance = None

def get_fantasy_service(db: Session = Depends(get_db)) -> FantasyService:
    """Get fantasy service with registered platforms"""
    global fantasy_service_instance
    
    if fantasy_service_instance is None:
        fantasy_service_instance = FantasyService(db)
        # Register platform interfaces
        fantasy_service_instance.register_platform(FantasyPlatform.SLEEPER, SleeperFantasyService())
    
    # Update database session (since it changes per request)
    fantasy_service_instance.db = db
    return fantasy_service_instance

class ConnectAccountRequest(BaseModel):
    platform: FantasyPlatform
    credentials: dict

@app.post("/api/fantasy/connect")
async def connect_fantasy_account(
    request: ConnectAccountRequest,
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Connect a user's fantasy sports account"""
    try:
        result = await fantasy_service.connect_user_account(
            user_id=current_user.id,
            platform=request.platform,
            credentials=request.credentials
        )
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Successfully connected {request.platform} account",
                "fantasy_user_id": result["fantasy_user_id"]
            }
        else:
            return {
                "success": False,
                "message": "Failed to connect account",
                "error": result.get("error")
            }
            
    except Exception as e:
        logger.error(f"Error connecting fantasy account: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fantasy/accounts")
async def get_fantasy_accounts(
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get all connected fantasy accounts for the user"""
    try:
        accounts = fantasy_service.get_user_fantasy_accounts(current_user.id)
        
        return {
            "success": True,
            "accounts": [
                {
                    "id": account["id"],
                    "platform": account["platform"],
                    "username": account["username"],
                    "last_sync": account["last_sync"].isoformat() if account["last_sync"] else None,
                    "league_count": account["league_count"]
                }
                for account in accounts
            ]
        }
        
    except Exception as e:
        logger.error(f"Error getting fantasy accounts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fantasy/leagues")
async def get_fantasy_leagues(
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get all fantasy leagues for the user"""
    try:
        leagues = fantasy_service.get_user_leagues(current_user.id)
        
        return {
            "success": True,
            "leagues": [
                {
                    "id": league["id"],
                    "name": league["name"],
                    "platform": league["platform"],
                    "season": league["season"],
                    "team_count": league["team_count"],
                    "scoring_type": league["scoring_type"],
                    "last_sync": league["last_sync"].isoformat() if league["last_sync"] else None,
                    "user_team": league["user_team"]
                }
                for league in leagues
            ]
        }
        
    except Exception as e:
        logger.error(f"Error getting fantasy leagues: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/fantasy/sync/{fantasy_user_id}")
async def sync_fantasy_leagues(
    fantasy_user_id: int,
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Manually sync leagues for a fantasy account"""
    try:
        # Verify the fantasy user belongs to current user
        accounts = fantasy_service.get_user_fantasy_accounts(current_user.id)
        if not any(acc["id"] == fantasy_user_id for acc in accounts):
            raise HTTPException(status_code=403, detail="Fantasy account not found or not owned by user")
        
        # Run sync
        result = await fantasy_service.sync_user_leagues(fantasy_user_id)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing fantasy leagues: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/fantasy/disconnect/{fantasy_user_id}")
async def disconnect_fantasy_account(
    fantasy_user_id: int,
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Disconnect a fantasy sports account"""
    try:
        result = fantasy_service.disconnect_fantasy_account(current_user.id, fantasy_user_id)
        return result
            
    except Exception as e:
        logger.error(f"Error disconnecting fantasy account: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fantasy/recommendations/start-sit/{week}")
async def get_start_sit_recommendations(
    week: int,
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get start/sit recommendations for the current week"""
    try:
        recommendations = await fantasy_service.generate_start_sit_recommendations(
            current_user.id, week
        )
        
        return {
            "success": True,
            "week": week,
            "recommendations": recommendations
        }
        
    except Exception as e:
        logger.error(f"Error getting start/sit recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fantasy/recommendations/waiver-wire/{week}")
async def get_waiver_wire_recommendations(
    week: int,
    current_user = Depends(get_current_user),
    fantasy_service: FantasyService = Depends(get_fantasy_service)
):
    """Get waiver wire pickup recommendations"""
    try:
        recommendations = await fantasy_service.generate_waiver_wire_recommendations(
            current_user.id, week
        )
        
        return {
            "success": True,
            "week": week,
            "recommendations": recommendations
        }
        
    except Exception as e:
        logger.error(f"Error getting waiver wire recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Test endpoints for Sleeper API
@app.get("/api/fantasy/test/sleeper/{username}")
async def test_sleeper_user(username: str):
    """Test endpoint to verify Sleeper API integration"""
    try:
        sleeper_service = SleeperFantasyService()
        
        # Test authentication
        auth_result = await sleeper_service.authenticate_user({"username": username})
        
        # Test getting leagues
        leagues = await sleeper_service.get_user_leagues(auth_result["user_id"])
        
        return {
            "success": True,
            "user": auth_result,
            "leagues_count": len(leagues),
            "leagues": leagues[:3]  # Return first 3 leagues for testing
        }
        
    except Exception as e:
        logger.error(f"Error testing Sleeper integration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fantasy/test/sleeper-trending")
async def test_sleeper_trending():
    """Test endpoint for Sleeper trending players"""
    try:
        sleeper_service = SleeperFantasyService()
        
        # Get trending adds and drops
        trending_adds = await sleeper_service.get_trending_players("add")
        trending_drops = await sleeper_service.get_trending_players("drop")
        
        return {
            "success": True,
            "trending_adds": trending_adds[:10],
            "trending_drops": trending_drops[:10]
        }
        
    except Exception as e:
        logger.error(f"Error testing Sleeper trending: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Live Sports Data API endpoints (The Odds API integration)
@app.get("/api/sports")
async def get_available_sports():
    """Get list of available sports from The Odds API"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    try:
        # Define allowed sports - only show these on the site
        ALLOWED_SPORTS = {
            'baseball_mlb',
            'basketball_nba', 
            'icehockey_nhl',
            'americanfootball_nfl',
            'americanfootball_ncaaf',
            'basketball_ncaab',
            'basketball_wnba',
            'soccer_epl',
            'soccer_mls'
        }
        
        # Check cache first
        cached_data = await cache_service.get_sports_list()
        if cached_data:
            logger.info("Returning cached sports list")
            return cached_data
        
        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            sports = await service.get_sports()
            
            # Filter to active sports only and add sport categories
            active_sports = []
            for sport in sports:
                # Only include allowed sports
                if sport.get("active", False) and sport["key"] in ALLOWED_SPORTS:
                    # Add sport category based on title/key
                    category = "Other"
                    if "football" in sport["key"].lower():
                        category = "Football"
                    elif "basketball" in sport["key"].lower():
                        category = "Basketball"
                    elif "baseball" in sport["key"].lower():
                        category = "Baseball"
                    elif "hockey" in sport["key"].lower():
                        category = "Hockey"
                    elif "soccer" in sport["key"].lower():
                        category = "Soccer"
                    elif "tennis" in sport["key"].lower():
                        category = "Tennis"
                    elif "golf" in sport["key"].lower():
                        category = "Golf"
                    elif "mma" in sport["key"].lower() or "boxing" in sport["key"].lower():
                        category = "Combat Sports"
                    
                    sport["category"] = category
                    active_sports.append(sport)
            
            result = {
                "status": "success",
                "count": len(active_sports),
                "sports": active_sports,
                "last_updated": datetime.now().isoformat(),
                "cached": False,
                "filtered": True,
                "allowed_sports": list(ALLOWED_SPORTS)
            }
            
            # Cache the result for 6 hours (sports list rarely changes)
            await cache_service.set_sports_list(result, expire_seconds=21600)
            logger.info(f"Cached filtered sports list with {len(active_sports)} sports")
            
            return result
            
    except Exception as e:
        logger.error(f"Error fetching sports list: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching sports: {str(e)}")

@app.get("/api/odds/popular")
async def get_popular_sports_odds():
    """Get odds for popular sports (NFL, NBA, MLB, NHL)"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    try:
        from app.services.odds_api_service import get_popular_sports_odds
        
        games = await get_popular_sports_odds()
        
        # Convert to serializable format
        games_data = []
        for game in games:
            bookmakers_data = []
            for bookmaker in game.bookmakers:
                bookmakers_data.append({
                    "key": bookmaker.key,
                    "title": bookmaker.title,
                    "last_update": bookmaker.last_update.isoformat(),
                    "markets": bookmaker.markets
                })
            
            games_data.append({
                "id": game.id,
                "sport_key": game.sport_key,
                "sport_title": game.sport_title,
                "commence_time": game.commence_time.isoformat(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "bookmakers": bookmakers_data
            })
        
        return {
            "status": "success",
            "count": len(games_data),
            "games": games_data,
            "sports_included": ["NFL", "NBA", "MLB", "NHL"],
            "rate_limit": await get_rate_limit_info(),
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error fetching popular sports odds: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching popular odds: {str(e)}")

@app.get("/api/odds/{sport_key}")
async def get_live_odds(
    sport_key: str,
    regions: str = "us",
    markets: str = "h2h,spreads,totals",
    odds_format: str = "american",
    bookmakers: str = None
):
    """Get live odds for a specific sport"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    try:
        # Check cache first
        cached_data = await cache_service.get_odds(
            sport_key, regions, markets, odds_format, bookmakers
        )
        if cached_data:
            logger.info(f"Returning cached odds for {sport_key}")
            cached_data["cached"] = True
            return cached_data
        
        # Validate sport key
        valid_sports = [sport.value for sport in SportKey]
        if sport_key not in valid_sports and sport_key not in [sport.name.lower() for sport in SportKey]:
            # Try to find a matching sport key
            sport_key_mapping = {sport.name.lower(): sport.value for sport in SportKey}
            sport_key = sport_key_mapping.get(sport_key.lower(), sport_key)
        
        # Validate odds format
        format_enum = OddsFormat.AMERICAN if odds_format.lower() == "american" else OddsFormat.DECIMAL
        
        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            games = await service.get_odds(
                sport=sport_key,
                regions=regions,
                markets=markets,
                odds_format=format_enum,
                bookmakers=bookmakers
            )
            
            # Convert to serializable format
            games_data = []
            for game in games:
                bookmakers_data = []
                for bookmaker in game.bookmakers:
                    bookmakers_data.append({
                        "key": bookmaker.key,
                        "title": bookmaker.title,
                        "last_update": bookmaker.last_update.isoformat(),
                        "markets": bookmaker.markets
                    })
                
                games_data.append({
                    "id": game.id,
                    "sport_key": game.sport_key,
                    "sport_title": game.sport_title,
                    "commence_time": game.commence_time.isoformat(),
                    "home_team": game.home_team,
                    "away_team": game.away_team,
                    "bookmakers": bookmakers_data
                })
            
            result = {
                "status": "success",
                "sport": sport_key,
                "count": len(games_data),
                "games": games_data,
                "rate_limit": await get_rate_limit_info(),
                "last_updated": datetime.now().isoformat(),
                "cached": False
            }
            
            # Cache odds for 2 hours (balance freshness with API usage)
            await cache_service.set_odds(
                sport_key, regions, markets, odds_format, result, 
                bookmakers, expire_seconds=7200
            )
            logger.info(f"Cached odds for {sport_key} with {len(games_data)} games")
            
            return result
            
    except Exception as e:
        logger.error(f"Error fetching odds for {sport_key}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching odds: {str(e)}")

@app.get("/api/scores/{sport_key}")
async def get_game_scores(
    sport_key: str,
    days_from: int = 3
):
    """Get scores and results for completed games"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    # Validate days_from parameter
    if days_from < 1 or days_from > 3:
        raise HTTPException(status_code=400, detail="days_from must be between 1 and 3")
    
    try:
        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            scores = await service.get_scores(
                sport=sport_key,
                days_from=days_from
            )
            
            # Convert to serializable format
            scores_data = []
            for score in scores:
                scores_data.append({
                    "id": score.id,
                    "sport_key": score.sport_key,
                    "sport_title": score.sport_title,
                    "commence_time": score.commence_time.isoformat(),
                    "home_team": score.home_team,
                    "away_team": score.away_team,
                    "completed": score.completed,
                    "home_score": score.home_score,
                    "away_score": score.away_score,
                    "last_update": score.last_update.isoformat()
                })
            
            return {
                "status": "success",
                "sport": sport_key,
                "days_from": days_from,
                "count": len(scores_data),
                "scores": scores_data,
                "rate_limit": await get_rate_limit_info(),
                "last_updated": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error fetching scores for {sport_key}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching scores: {str(e)}")

@app.get("/api/odds/{sport_key}/event/{event_id}")
async def get_event_odds(
    sport_key: str,
    event_id: str,
    regions: str = "us",
    markets: str = "h2h,spreads,totals",
    odds_format: str = "american",
    bookmakers: str = None
):
    """Get odds for a specific game/event"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    try:
        format_enum = OddsFormat.AMERICAN if odds_format.lower() == "american" else OddsFormat.DECIMAL
        
        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            game = await service.get_event_odds(
                sport=sport_key,
                event_id=event_id,
                regions=regions,
                markets=markets,
                odds_format=format_enum,
                bookmakers=bookmakers
            )
            
            if not game:
                raise HTTPException(status_code=404, detail="Event not found")
            
            # Convert to serializable format
            bookmakers_data = []
            for bookmaker in game.bookmakers:
                bookmakers_data.append({
                    "key": bookmaker.key,
                    "title": bookmaker.title,
                    "last_update": bookmaker.last_update.isoformat(),
                    "markets": bookmaker.markets
                })
            
            game_data = {
                "id": game.id,
                "sport_key": game.sport_key,
                "sport_title": game.sport_title,
                "commence_time": game.commence_time.isoformat(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "bookmakers": bookmakers_data
            }
            
            return {
                "status": "success",
                "event_id": event_id,
                "game": game_data,
                "rate_limit": await get_rate_limit_info(),
                "last_updated": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error fetching event odds for {event_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching event odds: {str(e)}")

@app.get("/api/odds/live")
async def get_live_games():
    """Get games that are currently live or starting soon"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    try:
        from app.services.odds_api_service import get_live_games
        
        games = await get_live_games()
        
        # Convert to serializable format
        games_data = []
        for game in games:
            bookmakers_data = []
            for bookmaker in game.bookmakers:
                bookmakers_data.append({
                    "key": bookmaker.key,
                    "title": bookmaker.title,
                    "last_update": bookmaker.last_update.isoformat(),
                    "markets": bookmaker.markets
                })
            
            games_data.append({
                "id": game.id,
                "sport_key": game.sport_key,
                "sport_title": game.sport_title,
                "commence_time": game.commence_time.isoformat(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "bookmakers": bookmakers_data
            })
        
        return {
            "status": "success",
            "count": len(games_data),
            "games": games_data,
            "description": "Games starting within the next 2 hours",
            "rate_limit": await get_rate_limit_info(),
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error fetching live games: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching live games: {str(e)}")

async def get_rate_limit_info():
    """Helper function to get rate limit information"""
    try:
        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            return service.get_rate_limit_status()
    except:
        return {
            "api_requests_used": 0,
            "api_requests_remaining": 500,
            "daily_requests": 0,
            "daily_limit": 700,
            "monthly_requests": 0,
            "monthly_limit": 20000,
            "last_request_time": 0
        }

@app.get("/api/cache/status")
async def get_cache_status():
    """Get cache system status and statistics"""
    try:
        stats = await cache_service.get_cache_stats()
        return {
            "status": "success",
            "cache_stats": stats,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting cache status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting cache status: {str(e)}")

@app.get("/api/usage/stats")
async def get_usage_stats():
    """Get detailed API usage statistics for rate limit monitoring"""
    if not settings.ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="The Odds API key not configured")
    
    try:
        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            usage_stats = service.get_usage_stats()
            rate_limit_status = service.get_rate_limit_status()
            
            return {
                "status": "success",
                "usage_stats": usage_stats,
                "rate_limit_status": rate_limit_status,
                "last_updated": datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"Error getting usage stats: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting usage stats: {str(e)}")

@app.post("/api/cache/clear")
async def clear_cache():
    """Clear all cached data (admin only)"""
    try:
        await cache_service.clear_pattern("odds_api:*")
        return {
            "status": "success",
            "message": "Cache cleared successfully",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")

@app.post("/api/cache/clear/{sport_key}")
async def clear_sport_cache(sport_key: str):
    """Clear cached data for a specific sport"""
    try:
        await cache_service.invalidate_sport_caches(sport_key)
        return {
            "status": "success",
            "message": f"Cache cleared for sport: {sport_key}",
            "sport": sport_key,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error clearing cache for {sport_key}: {e}")
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")

# Scheduler endpoints
@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """Get status of all scheduled tasks"""
    try:
        task_status = scheduler_service.get_task_status()
        return {
            "status": "success",
            "scheduler_running": scheduler_service.running,
            "task_count": len(task_status),
            "tasks": task_status,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting scheduler status: {str(e)}")

@app.post("/api/scheduler/task/{task_name}/run")
async def run_task_manually(task_name: str):
    """Manually trigger a scheduled task to run immediately"""
    try:
        await scheduler_service.run_task_now(task_name)
        return {
            "status": "success",
            "message": f"Task '{task_name}' executed successfully",
            "task_name": task_name,
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error running task {task_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error running task: {str(e)}")

@app.post("/api/scheduler/task/{task_name}/enable")
async def enable_task(task_name: str):
    """Enable a scheduled task"""
    try:
        scheduler_service.enable_task(task_name)
        return {
            "status": "success",
            "message": f"Task '{task_name}' enabled",
            "task_name": task_name,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error enabling task {task_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error enabling task: {str(e)}")

@app.post("/api/scheduler/task/{task_name}/disable")
async def disable_task(task_name: str):
    """Disable a scheduled task"""
    try:
        scheduler_service.disable_task(task_name)
        return {
            "status": "success",
            "message": f"Task '{task_name}' disabled",
            "task_name": task_name,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error disabling task {task_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error disabling task: {str(e)}")

@app.post("/api/scheduler/start")
async def start_scheduler():
    """Start the scheduler service"""
    try:
        await scheduler_service.start()
        return {
            "status": "success",
            "message": "Scheduler started",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Error starting scheduler: {str(e)}")

@app.post("/api/scheduler/stop")
async def stop_scheduler():
    """Stop the scheduler service"""
    try:
        await scheduler_service.stop()
        return {
            "status": "success",
            "message": "Scheduler stopped",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
        raise HTTPException(status_code=500, detail=f"Error stopping scheduler: {str(e)}")

# Auth endpoints
@app.post("/api/auth/verify-email")
async def verify_email(data: dict):
    """Verify user email with token"""
    token = data.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")
    
    result = await auth_service.verify_email(token)
    
    if result["success"]:
        return {
            "status": "success",
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.post("/api/auth/resend-verification")
async def resend_verification(data: dict):
    """Resend verification email"""
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    result = await auth_service.resend_verification_email(email)
    
    if result["success"]:
        return {
            "status": "success",
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.post("/api/auth/forgot-password")
async def forgot_password(data: dict):
    """Request password reset"""
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    result = await auth_service.request_password_reset(email)
    
    return {
        "status": "success",
        "message": result["message"]
    }

@app.post("/api/auth/reset-password")
async def reset_password(data: dict):
    """Reset password with token"""
    token = data.get("token")
    new_password = data.get("new_password")
    
    if not token or not new_password:
        raise HTTPException(status_code=400, detail="Token and new password are required")
    
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    result = await auth_service.reset_password(token, new_password)
    
    if result["success"]:
        return {
            "status": "success",
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.post("/api/auth/signup")
async def signup(user_data: UserSignup):
    """Create a new user account"""
    try:
        result = await auth_service.create_user(
            email=user_data.email,
            username=user_data.username,
            password=user_data.password,
            first_name=user_data.first_name,
            last_name=user_data.last_name
        )
        
        if result.get("success"):
            return {
                "status": "success",
                "message": "Account created successfully",
                "user": result["user"],
                "access_token": result["access_token"],
                "token_type": result["token_type"]
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")

@app.post("/api/auth/login")
async def login(user_data: UserLogin):
    """Authenticate user and return access token"""
    try:
        result = await auth_service.authenticate_user(
            email_or_username=user_data.email_or_username,
            password=user_data.password
        )
        
        if result["success"]:
            return {
                "status": "success",
                "message": "Login successful",
                "user": result["user"],
                "access_token": result["access_token"],
                "token_type": result["token_type"]
            }
        else:
            raise HTTPException(status_code=401, detail=result["error"])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

@app.get("/api/auth/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    return {
        "status": "success",
        "user": current_user
    }


# Google OAuth routes
@app.get("/api/auth/google/url")
async def get_google_auth_url():
    """Get Google OAuth authorization URL"""
    try:
        result = google_oauth_service.get_authorization_url()
        if 'error' in result:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": result['error']}
            )
        
        return {
            "status": "success",
            "authorization_url": result['authorization_url'],
            "state": result['state']
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Failed to get authorization URL: {str(e)}"}
        )


@app.get("/api/auth/google/callback")
async def google_oauth_callback(code: str, state: str):
    """Handle Google OAuth callback"""
    try:
        result = google_oauth_service.handle_callback(code, state)
        
        if 'error' in result:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": result['error']}
            )
        
        user_info = result['user_info']
        
        # Check if user already exists
        existing_user = await auth_service.get_user_by_email(user_info['email'])
        
        if existing_user:
            # User exists - log them in
            token_data = await auth_service.create_access_token(existing_user)
            
            # Update profile picture if provided
            if user_info.get('picture'):
                await auth_service.update_user_avatar(existing_user['id'], user_info['picture'])
            
            return {
                "status": "success",
                "message": "Login successful",
                "access_token": token_data["access_token"],
                "token_type": "bearer",
                "user": existing_user
            }
        else:
            # Create new user
            user_data = {
                "email": user_info['email'],
                "password": "google_oauth",  # Placeholder password
                "first_name": user_info['first_name'],
                "last_name": user_info['last_name'],
                "google_id": user_info['google_id'],
                "is_verified": user_info.get('email_verified', False),
                "avatar_url": user_info.get('picture', '')
            }
            
            result = await auth_service.create_user(user_data)
            
            if result["success"]:
                token_data = await auth_service.create_access_token(result["user"])
                return {
                    "status": "success",
                    "message": "Account created and login successful",
                    "access_token": token_data["access_token"],
                    "token_type": "bearer",
                    "user": result["user"]
                }
            else:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "message": result["message"]}
                )
                
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"OAuth callback failed: {str(e)}"}
        )


@app.post("/api/auth/google/verify")
async def verify_google_token(data: dict):
    """Verify Google ID token (for client-side OAuth)"""
    try:
        id_token = data.get('id_token')
        if not id_token:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "ID token is required"}
            )
        
        user_info = google_oauth_service.verify_id_token(id_token)
        if not user_info:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Invalid ID token"}
            )
        
        # Check if user already exists
        existing_user = await auth_service.get_user_by_email(user_info['email'])
        
        if existing_user:
            # User exists - log them in
            token_data = await auth_service.create_access_token(existing_user)
            
            # Update profile picture if provided
            if user_info.get('picture'):
                await auth_service.update_user_avatar(existing_user['id'], user_info['picture'])
            
            return {
                "status": "success",
                "message": "Login successful",
                "access_token": token_data["access_token"],
                "token_type": "bearer",
                "user": existing_user
            }
        else:
            # Create new user
            user_data = {
                "email": user_info['email'],
                "password": "google_oauth",  # Placeholder password
                "first_name": user_info['first_name'],
                "last_name": user_info['last_name'],
                "google_id": user_info['google_id'],
                "is_verified": user_info.get('email_verified', False),
                "avatar_url": user_info.get('picture', '')
            }
            
            result = await auth_service.create_user(user_data)
            
            if result["success"]:
                token_data = await auth_service.create_access_token(result["user"])
                return {
                    "status": "success",
                    "message": "Account created and login successful",
                    "access_token": token_data["access_token"],
                    "token_type": "bearer",
                    "user": result["user"]
                }
            else:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "message": result["message"]}
                )
                
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Token verification failed: {str(e)}"}
        )


@app.put("/api/auth/profile")
async def update_profile(
    profile_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update user profile including email and password"""
    try:
        # If changing password, verify current password first
        if "current_password" in profile_data and "new_password" in profile_data:
            user = auth_service.users.get(current_user["id"])
            if not user or not auth_service.verify_password(profile_data["current_password"], user["password_hash"]):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            
            # Update password
            profile_data["password"] = profile_data["new_password"]
            del profile_data["current_password"]
            del profile_data["new_password"]
        
        # Update user
        updated_user = await auth_service.update_user(current_user["id"], profile_data)
        
        if updated_user:
            return {
                "status": "success",
                "message": "Profile updated successfully",
                "user": updated_user
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to update profile")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating profile: {str(e)}")

@app.post("/api/auth/avatar")
async def upload_avatar(
    avatar_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Upload user avatar"""
    try:
        image_data = avatar_data.get("image_data")
        if not image_data:
            raise HTTPException(status_code=400, detail="Image data is required")
        
        # Get current user from database
        user = await auth_service.get_user_by_id(current_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete old avatar if exists
        if user.get("avatar_url"):
            avatar_service.delete_avatar(user["avatar_url"], user.get("avatar_thumbnail"))
        
        # Save new avatar
        success, result = avatar_service.save_avatar(current_user["id"], image_data)
        
        if success:
            # Update user record with avatar URLs in database
            update_result = await auth_service.update_user_avatar(
                current_user["id"],
                result["avatar"],
                result["thumbnail"]
            )
            
            if update_result["success"]:
                return {
                    "status": "success",
                    "message": "Avatar uploaded successfully",
                    "avatar_url": result["avatar"],
                    "thumbnail_url": result["thumbnail"]
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to update user avatar")
        else:
            raise HTTPException(status_code=400, detail=result)
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload avatar: {str(e)}")

@app.delete("/api/auth/avatar")
async def delete_avatar(current_user: dict = Depends(get_current_user)):
    """Delete user avatar"""
    try:
        # Get current user from database
        user = await auth_service.get_user_by_id(current_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete avatar files
        if user.get("avatar_url"):
            avatar_service.delete_avatar(user["avatar_url"], user.get("avatar_thumbnail"))
            
            # Clear avatar URLs from database
            update_result = await auth_service.update_user_avatar(
                current_user["id"],
                None,
                None
            )
            
            if update_result["success"]:
                return {
                    "status": "success",
                    "message": "Avatar deleted successfully"
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to update user avatar")
        else:
            raise HTTPException(status_code=400, detail="No avatar to delete")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete avatar: {str(e)}")

@app.get("/api/auth/avatar/{user_id}")
async def get_user_avatar(user_id: int):
    """Get user avatar URL"""
    try:
        # Get user from database
        user = await auth_service.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        avatar_url = avatar_service.get_avatar_url(user)
        
        return {
            "status": "success",
            "avatar_url": avatar_url,
            "thumbnail_url": user.get("avatar_thumbnail"),
            "has_custom_avatar": bool(user.get("avatar_url"))
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get avatar: {str(e)}")

@app.put("/api/auth/preferences")
async def update_preferences(
    preferences: UserPreferences,
    current_user: dict = Depends(get_current_user)
):
    """Update user preferences"""
    try:
        result = await auth_service.update_user_preferences(
            user_id=current_user["id"],
            preferences=preferences.dict(exclude_unset=True)
        )
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update preferences: {str(e)}")

@app.post("/api/auth/upgrade")
async def upgrade_subscription(
    upgrade_data: SubscriptionUpgrade,
    current_user: dict = Depends(get_current_user)
):
    """Upgrade user subscription"""
    try:
        # Validate tier
        valid_tiers = ["pro", "elite"]
        if upgrade_data.tier not in valid_tiers:
            raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {valid_tiers}")
        
        result = await auth_service.upgrade_subscription(
            user_id=current_user["id"],
            tier=upgrade_data.tier
        )
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"],
                "new_tier": upgrade_data.tier
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upgrade subscription: {str(e)}")

@app.post("/api/auth/demo-users")
async def create_demo_users():
    """Create demo users for testing"""
    try:
        auth_service.create_demo_users()
        return {
            "status": "success",
            "message": "Demo users created",
            "demo_accounts": [
                {"email": "demo@example.com", "password": "demo123", "tier": "free"},
                {"email": "pro@example.com", "password": "pro123", "tier": "pro"}
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create demo users: {str(e)}")

# Protected endpoint examples
@app.get("/api/predictions/personalized")
async def get_personalized_predictions(current_user: dict = Depends(get_current_user)):
    """Get predictions personalized for the current user"""
    try:
        # Use user's favorite teams and preferences
        import json
        favorite_teams = json.loads(current_user.get("favorite_teams", "[]"))
        preferred_sports = json.loads(current_user.get("preferred_sports", "[\"NFL\"]"))
        
        # Get regular predictions (you'd filter these based on user prefs)
        from app.services.data_pipeline import sports_pipeline
        games = await sports_pipeline.get_nfl_games_today()
        
        # Filter for user's favorite teams
        personalized_games = []
        for game in games:
            if (game.get("home_team") in favorite_teams or 
                game.get("away_team") in favorite_teams):
                personalized_games.append(game)
        
        return {
            "status": "success",
            "user_id": current_user["id"],
            "subscription_tier": current_user["subscription_tier"],
            "favorite_teams": favorite_teams,
            "personalized_games": personalized_games,
            "total_games": len(personalized_games)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting personalized predictions: {str(e)}")

@app.get("/api/user/performance")
async def get_user_performance(
    days: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """Get user's comprehensive betting performance analytics"""
    try:
        analytics = await betting_analytics_service.get_user_performance_analytics(
            user_id=current_user["id"],
            days=days
        )
        return analytics
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting user performance: {str(e)}")

# Bet endpoints
@app.post("/api/bets/place")
async def place_bet(
    bet_data: PlaceBetRequest,
    current_user: dict = Depends(get_current_user)
):
    """Place a single bet"""
    result = await bet_service.place_bet(current_user["id"], bet_data)
    
    if result["success"]:
        return {
            "status": "success",
            "bet": result["bet"],
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.post("/api/bets/parlay")
async def place_parlay(
    parlay_data: PlaceParlayRequest,
    current_user: dict = Depends(get_current_user)
):
    """Place a parlay bet"""
    result = await bet_service.place_parlay(current_user["id"], parlay_data)
    
    if result["success"]:
        return {
            "status": "success",
            "parlay": result["parlay"],
            "legs": result["legs"],
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.get("/api/bets/parlays")
async def get_user_parlays(
    current_user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    limit: int = 50
):
    """Get user's parlay bets"""
    result = await bet_service.get_user_parlays(current_user["id"], status, limit)
    
    if result["success"]:
        return {
            "status": "success",
            "parlays": result["parlays"],
            "total": result["total"]
        }
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch parlays"))

@app.get("/api/bets/parlay/{parlay_id}")
async def get_parlay_details(
    parlay_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get specific parlay details"""
    result = await bet_service.get_parlay_by_id(current_user["id"], parlay_id)
    
    if result["success"]:
        return {
            "status": "success",
            "parlay": result["parlay"]
        }
    else:
        raise HTTPException(status_code=404, detail=result.get("error", "Parlay not found"))

@app.post("/api/bets/history")
async def get_bet_history(
    query: BetHistoryQuery,
    current_user: dict = Depends(get_current_user)
):
    """Get user's bet history including live bets"""
    result = await bet_service.get_bet_history(current_user["id"], query)
    
    if result["success"]:
        # Also get live bets from database and format them for bet history
        live_bets = live_betting_service.get_user_live_bets(current_user["id"], include_settled=True)
        
        # Convert live bets to bet history format
        for live_bet in live_bets:
            # Create a descriptive title for live bets
            if live_bet.bet_type == "moneyline":
                if live_bet.selection == "home":
                    title = f"{live_bet.home_team} to Win"
                else:
                    title = f"{live_bet.away_team} to Win"
            elif live_bet.bet_type == "spread":
                if live_bet.selection == "home":
                    title = f"{live_bet.home_team} Spread"
                else:
                    title = f"{live_bet.away_team} Spread"
            elif live_bet.bet_type == "total":
                if live_bet.selection == "over":
                    title = f"Over Total ({live_bet.home_team} vs {live_bet.away_team})"
                else:
                    title = f"Under Total ({live_bet.home_team} vs {live_bet.away_team})"
            else:
                title = f"{live_bet.bet_type.title()} - {live_bet.selection.title()}"
            
            # Add to regular bets list with proper formatting
            bet_data = {
                "id": live_bet.id,
                "bet_type": "Live",
                "title": title,
                "status": live_bet.status.title(),
                "amount": live_bet.amount,
                "odds": live_bet.original_odds,
                "potential_win": live_bet.potential_win,
                "placed_at": live_bet.placed_at.isoformat(),
                "home_team": live_bet.home_team,
                "away_team": live_bet.away_team,
                "sport": live_bet.sport,
                "current_score": f"{live_bet.current_home_score or 0} - {live_bet.current_away_score or 0}" if live_bet.current_home_score is not None else None,
                "game_time": live_bet.current_game_status.value if live_bet.current_game_status else None,
                "selection": live_bet.selection
            }
            result["bets"].append(bet_data)
        
        # Sort by placed_at date (newest first)
        result["bets"].sort(key=lambda x: x["placed_at"], reverse=True)
        result["total"] = len(result["bets"])
        
        return {
            "status": "success",
            "bets": result["bets"],
            "total": result["total"],
            "offset": result.get("offset", query.offset),
            "limit": result.get("limit", query.limit)
        }
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch bet history"))

@app.get("/api/bets/stats")
async def get_bet_stats(current_user: dict = Depends(get_current_user)):
    """Get user's betting statistics"""
    result = await bet_service.get_bet_stats(current_user["id"])
    
    if result["success"]:
        return {
            "status": "success",
            "stats": result["stats"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.delete("/api/bets/{bet_id}")
async def cancel_bet(
    bet_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Cancel a pending bet"""
    result = await bet_service.cancel_bet(current_user["id"], bet_id)
    
    if result["success"]:
        return {
            "status": "success",
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.post("/api/bets/simulate")
async def simulate_bet_results(current_user: dict = Depends(get_current_user)):
    """Simulate bet results for demo purposes"""
    result = await bet_service.simulate_bet_results(current_user["id"])
    
    if result["success"]:
        return {
            "status": "success",
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

# Live Betting Endpoints
@app.post("/api/live-bets/place")
async def place_live_bet(
    request: PlaceLiveBetRequest,
    current_user: dict = Depends(get_current_user)
):
    """Place a live bet during an active game"""
    try:
        result = live_betting_service.place_live_bet(current_user["id"], request)
        
        if result.success:
            # Notify via WebSocket
            await manager.send_personal_message(
                {
                    "type": "live_bet_placed",
                    "bet": result.bet.dict() if result.bet else None,
                    "timestamp": datetime.now().isoformat()
                },
                current_user["id"]
            )
            
            return {
                "status": "success",
                "bet": result.bet,
                "odds_changed": result.odds_changed,
                "new_odds": result.new_odds
            }
        else:
            raise HTTPException(status_code=400, detail=result.error)
            
    except Exception as e:
        logger.error(f"Error placing live bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to place live bet")

@app.get("/api/live-bets/cash-out/{bet_id}")
async def get_cash_out_offer(
    bet_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get current cash out offer for a live bet"""
    try:
        offer = live_betting_service.get_cash_out_offer(bet_id, current_user["id"])
        
        if not offer:
            raise HTTPException(status_code=404, detail="Bet not found or cash out not available")
        
        return {
            "status": "success",
            "offer": offer
        }
        
    except Exception as e:
        logger.error(f"Error getting cash out offer: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cash out offer")

@app.post("/api/live-bets/cash-out")
async def execute_cash_out(
    request: CashOutRequest,
    current_user: dict = Depends(get_current_user)
):
    """Execute cash out for a live bet"""
    try:
        # Get current offer first
        offer = live_betting_service.get_cash_out_offer(request.bet_id, current_user["id"])
        
        if not offer or not offer.is_available:
            raise HTTPException(status_code=400, detail="Cash out not available")
        
        # Use current offer amount if not specified
        accept_amount = request.accept_amount or offer.current_cash_out_value
        
        result = live_betting_service.execute_cash_out(
            request.bet_id, 
            current_user["id"], 
            accept_amount
        )
        
        if result["success"]:
            # Notify via WebSocket
            await manager.send_personal_message(
                {
                    "type": "cash_out_executed",
                    "bet_id": request.bet_id,
                    "amount": result["cash_out_amount"],
                    "profit_loss": result["profit_loss"],
                    "timestamp": datetime.now().isoformat()
                },
                current_user["id"]
            )
            
            return {
                "status": "success",
                "cash_out_amount": result["cash_out_amount"],
                "profit_loss": result["profit_loss"],
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing cash out: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute cash out")

@app.get("/api/live-bets/markets")
async def get_live_betting_markets(
    sport: Optional[str] = None
):
    """Get available live betting markets with real sports data (public endpoint)"""
    try:
        print(f"Live betting markets endpoint called with sport: {sport}")
        markets = await live_betting_service.get_live_betting_markets(sport)
        print(f"Service returned {len(markets)} markets")
        
        return {
            "status": "success",
            "count": len(markets),
            "markets": markets
        }
        
    except Exception as e:
        print(f"Exception in live betting endpoint: {e}")
        logger.error(f"Error getting live markets: {e}")
        raise HTTPException(status_code=500, detail="Failed to get live markets")

@app.get("/api/live-bets/active")
async def get_user_live_bets(
    include_settled: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """Get user's active live bets"""
    try:
        bets = live_betting_service.get_user_live_bets(current_user["id"], include_settled)
        
        return {
            "status": "success",
            "count": len(bets),
            "bets": bets
        }
        
    except Exception as e:
        logger.error(f"Error getting user live bets: {e}")
        raise HTTPException(status_code=500, detail="Failed to get live bets")

@app.get("/api/live-bets/history/{bet_id}")
async def get_live_bet_details(
    bet_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get detailed history of a live bet including cash out info"""
    try:
        bet = live_betting_service.live_bets.get(bet_id)
        
        if not bet or bet.user_id != current_user["id"]:
            raise HTTPException(status_code=404, detail="Bet not found")
        
        # Get cash out history if applicable
        cash_out_history = None
        for history in live_betting_service.cash_out_history:
            if history.bet_id == bet_id:
                cash_out_history = history
                break
        
        return {
            "status": "success",
            "bet": bet,
            "cash_out_history": cash_out_history
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting live bet details: {e}")
        raise HTTPException(status_code=500, detail="Failed to get bet details")

@app.post("/api/live-bets/simulate")
async def start_live_betting_simulation(
    current_user: dict = Depends(get_current_user)
):
    """Start live betting simulation for testing (requires authentication)"""
    try:
        await live_betting_simulator.start_simulation()
        
        return {
            "status": "success",
            "message": "Live betting simulation started",
            "info": "Simulating 2 live games with dynamic odds and scores"
        }
        
    except Exception as e:
        logger.error(f"Error starting simulation: {e}")
        raise HTTPException(status_code=500, detail="Failed to start simulation")

@app.post("/api/live-bets/simulate/stop")
async def stop_live_betting_simulation(
    current_user: dict = Depends(get_current_user)
):
    """Stop live betting simulation"""
    try:
        await live_betting_simulator.stop_simulation()
        
        return {
            "status": "success",
            "message": "Live betting simulation stopped"
        }
        
    except Exception as e:
        logger.error(f"Error stopping simulation: {e}")
        raise HTTPException(status_code=500, detail="Failed to stop simulation")

# YetAI Bets API endpoints (Admin-created best bets)
async def get_current_user_from_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from authentication token"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization required")
    
    user = await auth_service.get_user_by_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return user

async def require_admin(user: dict = Depends(get_current_user_from_auth)):
    """Require admin privileges"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user

@app.get("/api/yetai-bets")
async def get_yetai_bets(user: dict = Depends(get_current_user_from_auth)):
    """Get YetAI Bets for the current user based on their tier"""
    try:
        user_tier = user.get("subscription_tier", "free")
        bets = await yetai_bets_service.get_active_bets(user_tier)
        stats = await yetai_bets_service.get_performance_stats()
        
        return {
            "status": "success",
            "bets": bets,
            "performance_stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting YetAI bets: {e}")
        raise HTTPException(status_code=500, detail="Failed to get bets")

@app.get("/api/admin/yetai-bets")
async def get_all_yetai_bets(admin_user: dict = Depends(require_admin)):
    """Get all YetAI Bets for admin management"""
    try:
        bets = await yetai_bets_service.get_all_bets()
        stats = await yetai_bets_service.get_performance_stats()
        
        return {
            "status": "success",
            "bets": bets,
            "performance_stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting all YetAI bets: {e}")
        raise HTTPException(status_code=500, detail="Failed to get bets")

@app.post("/api/admin/yetai-bets")
async def create_yetai_bet(bet_request: CreateYetAIBetRequest, admin_user: dict = Depends(require_admin)):
    """Create a new YetAI Bet (Admin only)"""
    try:
        result = await yetai_bets_service.create_bet(bet_request, admin_user["id"])
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"],
                "bet_id": result["bet_id"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating YetAI bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to create bet")

@app.post("/api/admin/yetai-bets/parlay")
async def create_yetai_parlay(parlay_request: CreateParlayBetRequest, admin_user: dict = Depends(require_admin)):
    """Create a new YetAI Parlay Bet (Admin only)"""
    try:
        result = await yetai_bets_service.create_parlay(parlay_request, admin_user["id"])
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"],
                "bet_id": result["bet_id"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating YetAI parlay: {e}")
        raise HTTPException(status_code=500, detail="Failed to create parlay")

@app.put("/api/admin/yetai-bets/{bet_id}")
async def update_yetai_bet(bet_id: str, update_request: UpdateYetAIBetRequest, admin_user: dict = Depends(require_admin)):
    """Update a YetAI Bet (Admin only)"""
    try:
        result = await yetai_bets_service.update_bet(bet_id, update_request, admin_user["id"])
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating YetAI bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to update bet")

@app.delete("/api/admin/yetai-bets/{bet_id}")
async def delete_yetai_bet(bet_id: str, admin_user: dict = Depends(require_admin)):
    """Delete a YetAI Bet (Admin only)"""
    try:
        result = await yetai_bets_service.delete_bet(bet_id, admin_user["id"])
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting YetAI bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete bet")

@app.delete("/api/admin/users/{user_id}/bets")
async def delete_all_user_bets(user_id: int, admin_user: dict = Depends(require_admin)):
    """Delete all bets for a specific user (Admin only - for testing purposes)"""
    try:
        # Import database models and session
        from app.core.database import SessionLocal
        from app.models.database_models import Bet, LiveBet as LiveBetDB, ParlayBet, YetAIBet
        
        deleted_counts = {"regular_bets": 0, "live_bets": 0, "parlay_bets": 0, "yetai_bets": 0}
        
        db = SessionLocal()
        try:
            # Delete regular bets
            regular_bets = db.query(Bet).filter(Bet.user_id == user_id).all()
            regular_count = len(regular_bets)
            for bet in regular_bets:
                db.delete(bet)
            deleted_counts["regular_bets"] = regular_count
            
            # Delete live bets
            live_bets = db.query(LiveBetDB).filter(LiveBetDB.user_id == user_id).all()
            live_count = len(live_bets)
            for bet in live_bets:
                db.delete(bet)
            deleted_counts["live_bets"] = live_count
            
            # Delete parlay bets
            parlay_bets = db.query(ParlayBet).filter(ParlayBet.user_id == user_id).all()
            parlay_count = len(parlay_bets)
            for bet in parlay_bets:
                db.delete(bet)
            deleted_counts["parlay_bets"] = parlay_count
            
            # Delete YetAI bets
            yetai_bets = db.query(YetAIBet).filter(YetAIBet.user_id == user_id).all()
            yetai_count = len(yetai_bets)
            for bet in yetai_bets:
                db.delete(bet)
            deleted_counts["yetai_bets"] = yetai_count
            
            db.commit()
            
            logger.info(f"Admin {admin_user['id']} deleted all bets for user {user_id}: {deleted_counts}")
            
            return {
                "status": "success",
                "message": f"Successfully deleted {deleted_counts['regular_bets']} regular bets, {deleted_counts['live_bets']} live bets, {deleted_counts['parlay_bets']} parlay bets, and {deleted_counts['yetai_bets']} YetAI bets for user {user_id}",
                "deleted_counts": deleted_counts
            }
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error deleting all bets for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user bets")

# Admin User Management Endpoints
class PromoteAdminRequest(BaseModel):
    email: EmailStr

class CreateAdminRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

@app.post("/api/auth/promote-admin")
async def promote_user_to_admin(request: PromoteAdminRequest, current_user: dict = Depends(require_admin)):
    """Promote a user to admin (admin only)"""
    try:
        # Find user by email
        target_user = None
        for user in auth_service.users.values():
            if user["email"] == request.email:
                target_user = user
                break
        
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Promote to admin
        target_user["is_admin"] = True
        target_user["subscription_tier"] = "elite"  # Admins get elite tier
        
        return {
            "status": "success",
            "message": f"User {request.email} promoted to admin",
            "user": {
                "email": target_user["email"],
                "first_name": target_user["first_name"],
                "last_name": target_user["last_name"],
                "is_admin": target_user["is_admin"],
                "subscription_tier": target_user["subscription_tier"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to promote user: {str(e)}")

@app.post("/api/auth/create-admin")
async def create_admin_user(request: CreateAdminRequest, current_user: dict = Depends(require_admin)):
    """Create a new admin user (admin only)"""
    try:
        result = await auth_service.create_admin_user(
            email=request.email,
            password=request.password,
            first_name=request.first_name,
            last_name=request.last_name
        )
        
        if result["success"]:
            return {
                "status": "success",
                "message": "Admin user created successfully",
                "user": result["user"],
                "access_token": result["access_token"],
                "token_type": result["token_type"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create admin user: {str(e)}")

# 2FA (Two-Factor Authentication) endpoints
@app.get("/api/auth/2fa/status")
async def get_2fa_status(current_user: dict = Depends(get_current_user)):
    """Get 2FA status for current user"""
    try:
        result = await auth_service.get_2fa_status(current_user["id"])
        
        if result["success"]:
            return {
                "status": "success",
                "enabled": result["enabled"],
                "backup_codes_remaining": result["backup_codes_remaining"],
                "setup_in_progress": result["setup_in_progress"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get 2FA status: {str(e)}")

@app.post("/api/auth/2fa/setup")
async def setup_2fa(current_user: dict = Depends(get_current_user)):
    """Setup 2FA - generate QR code and backup codes"""
    try:
        result = await auth_service.setup_2fa(current_user["id"])
        
        if result["success"]:
            return {
                "status": "success",
                "qr_code": result["qr_code"],
                "backup_codes": result["backup_codes"],
                "message": "Scan the QR code with your authenticator app"
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to setup 2FA: {str(e)}")

@app.post("/api/auth/2fa/enable")
async def enable_2fa(
    request: Enable2FARequest, 
    current_user: dict = Depends(get_current_user)
):
    """Enable 2FA after verifying the setup token"""
    try:
        result = await auth_service.enable_2fa(current_user["id"], request.token)
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enable 2FA: {str(e)}")

@app.post("/api/auth/2fa/disable")
async def disable_2fa(
    request: Disable2FARequest,
    current_user: dict = Depends(get_current_user)
):
    """Disable 2FA with password and 2FA verification"""
    try:
        result = await auth_service.disable_2fa(
            current_user["id"], 
            request.password, 
            request.token
        )
        
        if result["success"]:
            return {
                "status": "success",
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to disable 2FA: {str(e)}")

@app.get("/api/auth/2fa/backup-codes/status")
async def get_backup_codes_status(current_user: dict = Depends(get_current_user)):
    """Get backup codes status"""
    try:
        user = auth_service.users.get(current_user["id"])
        if not user or not user.get("totp_enabled"):
            raise HTTPException(status_code=400, detail="2FA is not enabled")
        
        backup_codes_str = user.get("backup_codes", "[]")
        backup_codes = json.loads(backup_codes_str) if backup_codes_str else []
        
        # For tracking used codes, we'd need to maintain a separate list
        # For now, we'll just return remaining codes
        return {
            "status": "success",
            "remaining_codes": backup_codes,
            "used_codes": [],  # Would need to track this separately
            "total_generated": len(backup_codes)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get backup codes status: {str(e)}")

@app.post("/api/auth/2fa/backup-codes/regenerate")
async def regenerate_backup_codes(current_user: dict = Depends(get_current_user)):
    """Regenerate backup codes"""
    try:
        user = auth_service.users.get(current_user["id"])
        if not user or not user.get("totp_enabled"):
            raise HTTPException(status_code=400, detail="2FA is not enabled")
        
        # Generate new backup codes
        from app.services.totp_service import totp_service
        new_codes = totp_service.generate_backup_codes()
        
        # Update user's backup codes
        user["backup_codes"] = json.dumps(new_codes)
        
        return {
            "status": "success",
            "backup_codes": new_codes,
            "message": "Backup codes regenerated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate backup codes: {str(e)}")

@app.post("/api/auth/2fa/backup-codes/email")
async def email_backup_codes(current_user: dict = Depends(get_current_user)):
    """Email backup codes to user"""
    try:
        user = auth_service.users.get(current_user["id"])
        if not user or not user.get("totp_enabled"):
            raise HTTPException(status_code=400, detail="2FA is not enabled")
        
        backup_codes_str = user.get("backup_codes", "[]")
        backup_codes = json.loads(backup_codes_str) if backup_codes_str else []
        
        if not backup_codes:
            raise HTTPException(status_code=400, detail="No backup codes available")
        
        # Send email with backup codes
        from app.services.email_service import email_service
        email_sent = email_service.send_2fa_backup_codes_email(
            to_email=user["email"],
            backup_codes=backup_codes,
            first_name=user.get("first_name")
        )
        
        if email_sent:
            return {
                "status": "success",
                "message": "Backup codes sent to your email"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to send email")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to email backup codes: {str(e)}")

@app.post("/api/auth/2fa/verify")
async def verify_2fa_token(
    request: Verify2FARequest,
    current_user: dict = Depends(get_current_user)
):
    """Verify a 2FA token (for testing or validation)"""
    try:
        is_valid = await auth_service.verify_2fa_token(current_user["id"], request.token)
        
        return {
            "status": "success",
            "valid": is_valid
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify 2FA token: {str(e)}")

# Admin user management endpoints
@app.get("/api/admin/users")
async def get_all_users(
    current_user: dict = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
    search: str = None
):
    """Get all users (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        users = await auth_service.get_all_users(skip=skip, limit=limit, search=search)
        return {
            "status": "success",
            "users": users,
            "total": len(users)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get users: {str(e)}")

@app.put("/api/admin/users/{user_id}")
async def update_user(
    user_id: int,
    update_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update user details (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Don't allow admins to modify their own admin status
        if user_id == current_user["id"] and "is_admin" in update_data:
            raise HTTPException(status_code=400, detail="Cannot modify your own admin status")
        
        # Check if email is being changed and validate it
        if "email" in update_data:
            existing_user = await auth_service.get_user_by_email(update_data["email"])
            if existing_user and existing_user["id"] != user_id:
                raise HTTPException(status_code=400, detail="Email already in use by another user")
        
        logger.info(f"Admin {current_user['id']} updating user {user_id} with data: {update_data}")
        updated_user = await auth_service.update_user(user_id, update_data)
        if updated_user:
            logger.info(f"User {user_id} updated successfully")
            return {
                "status": "success",
                "user": updated_user,
                "message": "User updated successfully"
            }
        else:
            logger.error(f"User {user_id} not found or update failed")
            raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user: {str(e)}")

@app.post("/api/admin/users")
async def create_user_admin(
    user_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create a new user (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Extract user data
        email = user_data.get("email")
        password = user_data.get("password", "password123")  # Default password if not provided
        first_name = user_data.get("first_name", "")
        last_name = user_data.get("last_name", "")
        subscription_tier = user_data.get("subscription_tier", "free")
        is_admin = user_data.get("is_admin", False)
        is_verified = user_data.get("is_verified", True)
        
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # Check if user already exists
        existing_user = await auth_service.get_user_by_email(email)
        if existing_user:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        
        # Create user
        new_user = await auth_service.create_user_admin(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            subscription_tier=subscription_tier,
            is_admin=is_admin,
            is_verified=is_verified
        )
        
        if new_user:
            return {
                "status": "success",
                "user": new_user,
                "message": f"User created successfully with password: {password}"
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to create user")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")

@app.delete("/api/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Delete a user (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Don't allow admins to delete themselves
        if user_id == current_user["id"]:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        
        success = await auth_service.delete_user(user_id)
        if success:
            return {
                "status": "success",
                "message": "User deleted successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")

@app.post("/api/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Reset user password (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        new_password = await auth_service.reset_user_password(user_id)
        if new_password:
            return {
                "status": "success",
                "temporary_password": new_password,
                "message": "Password reset successfully. Share this temporary password with the user."
            }
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset password: {str(e)}")

# WebSocket endpoints and startup events
@app.on_event("startup")
async def startup_event():
    """Start background tasks and initialize database"""
    # Initialize database connection and tables
    try:
        if not check_db_connection():
            logger.error("Database connection failed - switching to in-memory fallback")
        else:
            init_db()
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
    
    # Start background tasks for live updates
    asyncio.create_task(simulate_odds_updates())
    asyncio.create_task(simulate_score_updates())
    
    # Start the scheduler for live sports data updates
    await scheduler_service.start()
    
    # Start the bet verification scheduler
    init_scheduler()
    
    logger.info("WebSocket services, sports scheduler, bet verification scheduler, and database started")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    try:
        cleanup_scheduler()
        logger.info("Bet verification scheduler stopped")
    except Exception as e:
        logger.error(f"Error during scheduler cleanup: {e}")

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for live updates"""
    await manager.connect(websocket, user_id)
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            
            if data["type"] == "subscribe":
                await manager.subscribe_to_game(user_id, data["game_id"])
            elif data["type"] == "unsubscribe":
                await manager.unsubscribe_from_game(user_id, data["game_id"])
            elif data["type"] == "ping":
                await manager.send_personal_message({"type": "pong"}, user_id)
            else:
                logger.warning(f"Unknown message type: {data.get('type')}")
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
    finally:
        manager.disconnect(user_id)

# Bet Sharing Endpoints
@app.post("/api/bets/share")
async def create_shareable_bet_link(
    request: dict,
    current_user: dict = Depends(get_current_user)
):
    """Create a shareable link for a bet"""
    bet_id = request.get("bet_id")
    
    if not bet_id:
        raise HTTPException(status_code=400, detail="Bet ID is required")
    
    # First try to get from bet history
    bet_history_result = await bet_service.get_bet_history(current_user["id"], BetHistoryQuery(limit=100))
    
    if not bet_history_result["success"]:
        raise HTTPException(status_code=400, detail="Failed to retrieve bet data")
    
    # Find the specific bet
    bet_data = None
    for bet in bet_history_result["bets"]:
        if bet["id"] == bet_id:
            bet_data = bet
            break
    
    # If not found in regular bets, check parlays
    if not bet_data:
        parlay_result = await bet_service.get_user_parlays(current_user["id"], limit=100)
        if parlay_result["success"]:
            for parlay in parlay_result["parlays"]:
                if parlay["id"] == bet_id:
                    bet_data = parlay
                    # Ensure bet_type is set for parlays
                    bet_data["bet_type"] = "parlay"
                    break
    
    if not bet_data:
        raise HTTPException(status_code=404, detail="Bet not found")
    
    result = await bet_sharing_service.create_shareable_link(current_user["id"], bet_data)
    
    if result["success"]:
        return {
            "status": "success",
            "share_id": result["share_id"],
            "share_url": result["share_url"],
            "expires_at": result["expires_at"],
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.get("/api/share/bet/{share_id}")
async def get_shared_bet(share_id: str):
    """Get shared bet data (public endpoint)"""
    result = await bet_sharing_service.get_shared_bet(share_id)
    
    if result["success"]:
        return {
            "status": "success",
            "shared_bet": result["shared_bet"],
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=404, detail=result["error"])

@app.get("/api/bets/shared")
async def get_user_shared_bets(current_user: dict = Depends(get_current_user)):
    """Get all shared bets created by the current user"""
    result = await bet_sharing_service.get_user_shared_bets(current_user["id"])
    
    if result["success"]:
        return {
            "status": "success",
            "shared_bets": result["shared_bets"],
            "total": result["total"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.delete("/api/bets/shared/{share_id}")
async def delete_shared_bet(
    share_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a shared bet link"""
    result = await bet_sharing_service.delete_shared_bet(current_user["id"], share_id)
    
    if result["success"]:
        return {
            "status": "success",
            "message": result["message"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

# Bet Verification Endpoints (Admin Only)
@app.post("/api/admin/bets/verify")
async def trigger_bet_verification(current_user: dict = Depends(get_current_user)):
    """Manually trigger bet verification (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        result = await bet_scheduler.run_verification_now()
        return {
            "status": "success" if result.get("success", False) else "error",
            "data": result
        }
    except Exception as e:
        logger.error(f"Error triggering bet verification: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")

@app.get("/api/admin/bets/verification/stats")
async def get_verification_stats(current_user: dict = Depends(get_current_user)):
    """Get bet verification statistics and scheduler status (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        stats = bet_scheduler.get_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        logger.error(f"Error getting verification stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

@app.post("/api/admin/bets/verification/config")
async def update_verification_config(
    config: dict,
    current_user: dict = Depends(get_current_user)
):
    """Update bet verification scheduler configuration (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        result = bet_scheduler.update_config(config)
        if result.get("success", False):
            return {
                "status": "success",
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error", "Configuration update failed"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating verification config: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")

@app.post("/api/admin/bets/verification/reset-stats")
async def reset_verification_stats(current_user: dict = Depends(get_current_user)):
    """Reset bet verification statistics (admin only)"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        result = bet_scheduler.reset_stats()
        return {
            "status": "success",
            "message": result["message"]
        }
    except Exception as e:
        logger.error(f"Error resetting verification stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset stats: {str(e)}")

@app.get("/api/websocket/stats")
async def get_websocket_stats():
    """Get WebSocket connection statistics"""
    return {
        "status": "success",
        "stats": manager.get_connection_stats()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)