from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
from app.services.auth_service import auth_service
from app.services.bet_service import bet_service
from app.services.websocket_manager import manager, simulate_odds_updates, simulate_score_updates
from app.services.odds_api_service import OddsAPIService, SportKey, MarketKey, OddsFormat
from app.services.cache_service import cache_service
from app.services.scheduler_service import scheduler_service
from app.models.bet_models import *
from app.core.config import settings
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
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserPreferences(BaseModel):
    favorite_teams: Optional[list] = None
    preferred_sports: Optional[list] = None
    notification_settings: Optional[dict] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class SubscriptionUpgrade(BaseModel):
    tier: str  # "pro" or "elite"

app = FastAPI(
    title="AI Sports Betting MVP",
    description="AI-powered sports betting and fantasy insights platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

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
@app.post("/api/auth/signup")
async def signup(user_data: UserSignup):
    """Create a new user account"""
    try:
        result = await auth_service.create_user(
            email=user_data.email,
            password=user_data.password,
            first_name=user_data.first_name,
            last_name=user_data.last_name
        )
        
        if result["success"]:
            return {
                "status": "success",
                "message": "Account created successfully",
                "user": result["user"],
                "access_token": result["access_token"],
                "token_type": result["token_type"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")

@app.post("/api/auth/login")
async def login(user_data: UserLogin):
    """Authenticate user and return access token"""
    try:
        result = await auth_service.authenticate_user(
            email=user_data.email,
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
async def get_user_performance(current_user: dict = Depends(get_current_user)):
    """Get user's personal prediction performance"""
    try:
        # This would integrate with your performance tracker
        # For now, return mock user-specific data
        
        return {
            "status": "success",
            "user_id": current_user["id"],
            "personal_stats": {
                "predictions_made": 25,
                "accuracy_rate": 78.5,
                "best_sport": "NFL",
                "favorite_bet_type": "spreads",
                "total_profit": 125.50 if current_user["subscription_tier"] != "free" else "Upgrade to see profits"
            },
            "recent_predictions": [
                {"game": "Chiefs vs Bills", "prediction": "Chiefs -3", "result": "Won", "profit": 10.50},
                {"game": "Cowboys vs Eagles", "prediction": "Over 47.5", "result": "Lost", "profit": -11.00}
            ]
        }
        
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

@app.post("/api/bets/history")
async def get_bet_history(
    query: BetHistoryQuery,
    current_user: dict = Depends(get_current_user)
):
    """Get user's bet history"""
    result = await bet_service.get_bet_history(current_user["id"], query)
    
    if result["success"]:
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

# WebSocket endpoints and startup events
@app.on_event("startup")
async def startup_event():
    """Start background tasks for live updates"""
    asyncio.create_task(simulate_odds_updates())
    asyncio.create_task(simulate_score_updates())
    
    # Start the scheduler for live sports data updates
    await scheduler_service.start()
    
    logger.info("WebSocket services and scheduler started")

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