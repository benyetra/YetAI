"""
Environment-aware FastAPI application for YetAI Sports Betting MVP
Consolidates development and production functionality into a single file
"""
from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio
import json
import logging
import os
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any

# Import core configuration and service loader
from app.core.config import settings
from app.core.service_loader import initialize_services, get_service, is_service_available, require_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize services with graceful degradation
service_loader = initialize_services()

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

# Environment-aware CORS configuration
def get_cors_origins():
    """Get CORS origins based on environment using centralized configuration"""
    return settings.get_frontend_urls()

# Create FastAPI app
app = FastAPI(
    title="YetAI Sports Betting MVP",
    description=f"AI-Powered Sports Betting Platform - {settings.ENVIRONMENT.title()} Environment",
    version="1.2.0",
    debug=settings.DEBUG
)

# Add CORS middleware with environment-aware origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info(f"🚀 Starting YetAI Sports Betting MVP - {settings.ENVIRONMENT.upper()} Environment")
    
    # Initialize database if available
    if is_service_available("database"):
        try:
            database_service = get_service("database")
            if database_service and database_service["check_db_connection"]():
                logger.info("✅ Database connected successfully")
                database_service["init_db"]()
                logger.info("✅ Database tables initialized")
        except Exception as e:
            logger.warning(f"⚠️  Database initialization failed: {e}")
    
    # Initialize scheduler if available
    if is_service_available("scheduler_service"):
        try:
            scheduler = get_service("scheduler_service")
            if hasattr(scheduler, 'start'):
                await scheduler.start()
                logger.info("✅ Scheduler service started")
        except Exception as e:
            logger.warning(f"⚠️  Scheduler initialization failed: {e}")
    
    # Log service summary
    available_services = [name for name in service_loader.get_status() if service_loader.is_available(name)]
    logger.info(f"✅ Services online: {len(available_services)}/{len(service_loader.get_status())}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down YetAI Sports Betting MVP")
    
    # Cleanup scheduler if available
    if is_service_available("scheduler_service"):
        try:
            scheduler = get_service("scheduler_service")
            if hasattr(scheduler, 'stop'):
                await scheduler.stop()
                logger.info("✅ Scheduler service stopped")
        except Exception as e:
            logger.warning(f"⚠️  Scheduler cleanup failed: {e}")

# Health and status endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway/deployment monitoring"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat(),
        "services": service_loader.get_status()
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": f"YetAI Sports Betting MVP - {settings.ENVIRONMENT.title()} API",
        "version": "1.2.0",
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/health",
        "services_available": len([s for s in service_loader.get_status().values() if s]),
        "total_services": len(service_loader.get_status())
    }

@app.get("/api/status")
async def get_api_status():
    """Get comprehensive API status"""
    return {
        "api_status": "operational",
        "environment": settings.ENVIRONMENT,
        "services": service_loader.get_status(),
        "database_connected": is_service_available("database"),
        "auth_available": is_service_available("auth_service"),
        "sports_data_available": is_service_available("sports_pipeline"),
        "ai_chat_available": is_service_available("ai_chat_service"),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/endpoints/health")
async def get_endpoints_health():
    """Get health status of all API endpoints"""
    endpoints_status = {
        "core_endpoints": {
            "status": "operational",
            "endpoints": ["/health", "/", "/api/status", "/api/auth/status"]
        },
        "authentication": {
            "status": "operational" if is_service_available("auth_service") else "degraded",
            "endpoints": ["/api/auth/register", "/api/auth/login", "/api/auth/logout", "/api/auth/me"]
        },
        "sports_data": {
            "status": "operational" if is_service_available("sports_pipeline") else "degraded",
            "endpoints": ["/api/games/nfl", "/api/odds/popular", "/api/odds/nfl"]
        },
        "odds_markets": {
            "status": "operational" if settings.ODDS_API_KEY else "degraded",
            "endpoints": [
                "/api/odds/americanfootball_nfl", "/api/odds/basketball_nba", 
                "/api/odds/baseball_mlb", "/api/odds/icehockey_nhl", "/api/odds/hockey"
            ]
        },
        "betting": {
            "status": "operational" if is_service_available("bet_service") else "degraded",
            "endpoints": [
                "/api/bets/place", "/api/bets/parlay", "/api/bets/parlays", "/api/bets/stats",
                "/api/bets/share", "/api/bets/shared", "/api/bets/simulate", "/api/bets/history"
            ]
        },
        "parlays": {
            "status": "operational" if is_service_available("bet_service") else "degraded",
            "endpoints": ["/api/parlays/markets", "/api/parlays/popular"]
        },
        "fantasy": {
            "status": "operational" if (is_service_available("fantasy_pipeline") or is_service_available("real_fantasy_pipeline")) else "degraded",
            "endpoints": [
                "/api/fantasy/accounts", "/api/fantasy/leagues", "/api/fantasy/connect", 
                "/api/fantasy/roster/{league_id}", "/api/fantasy/projections"
            ]
        },
        "yetai_bets": {
            "status": "operational" if is_service_available("yetai_bets_service") else "degraded",
            "endpoints": ["/api/yetai-bets", "/api/admin/yetai-bets/{bet_id}"]
        },
        "live_betting": {
            "status": "operational" if is_service_available("bet_service") else "degraded",
            "endpoints": ["/api/live-bets/markets", "/api/live-bets/active"]
        },
        "profile": {
            "status": "operational" if is_service_available("auth_service") else "degraded",
            "endpoints": ["/api/profile/sports", "/api/profile/status"]
        },
        "ai_chat": {
            "status": "operational" if is_service_available("ai_chat_service") else "degraded",
            "endpoints": ["/api/chat/message", "/api/chat/suggestions"]
        }
    }
    
    # Calculate overall health
    operational_categories = len([cat for cat in endpoints_status.values() if cat["status"] == "operational"])
    total_categories = len(endpoints_status)
    overall_health = "healthy" if operational_categories >= total_categories * 0.7 else "degraded"
    
    return {
        "status": overall_health,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat(),
        "categories": endpoints_status,
        "summary": {
            "operational_categories": operational_categories,
            "total_categories": total_categories,
            "health_percentage": round((operational_categories / total_categories) * 100, 1)
        }
    }

# Authentication API endpoints
@app.get("/api/auth/status")
async def auth_status():
    """Check authentication status"""
    return {
        "authenticated": False,
        "auth_available": is_service_available("auth_service"),
        "message": "Authentication service ready" if is_service_available("auth_service") else "Authentication service unavailable"
    }

@app.post("/api/auth/register")
async def register(user_data: dict):
    """Register a new user"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, 
            detail="Authentication service is currently unavailable"
        )
    
    try:
        auth_service = get_service("auth_service")
        result = await auth_service.create_user(
            email=user_data.get("email"),
            password=user_data.get("password"),
            username=user_data.get("username", user_data.get("email")),  # Use username or fallback to email
            first_name=user_data.get("first_name", ""),
            last_name=user_data.get("last_name", "")
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Registration failed"))
            
        return {
            "status": "success",
            "message": "User registered successfully",
            "user": result.get("user"),
            "access_token": result.get("access_token")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
async def login(credentials: dict):
    """Login user"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, 
            detail="Authentication service is currently unavailable"
        )
    
    try:
        auth_service = get_service("auth_service")
        result = await auth_service.authenticate_user(
            email_or_username=credentials.get("email_or_username"),
            password=credentials.get("password")
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=401, detail=result.get("error", "Invalid credentials"))
            
        return {
            "status": "success",
            "message": "Login successful",
            "access_token": result.get("access_token"),
            "user": result.get("user")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/auth/logout")
async def logout():
    """Logout user"""
    return {
        "status": "success",
        "message": "Logged out successfully"
    }

@app.get("/api/auth/me")
async def get_current_user():
    """Get current user info"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503,
            detail="Authentication service is currently unavailable"
        )
    
    return {
        "status": "success",
        "message": "Authentication endpoint available but token validation not fully implemented",
        "user": None
    }

# Sports data endpoints
@app.get("/api/games/nfl")
async def get_nfl_games():
    """Get NFL games and scores"""
    if is_service_available("sports_pipeline"):
        try:
            sports_pipeline = get_service("sports_pipeline")
            games = await sports_pipeline.get_nfl_games()
            return {"status": "success", "games": games}
        except Exception as e:
            logger.error(f"Error fetching NFL games: {e}")
            # Fall through to mock data
    
    # Return mock data when service unavailable
    return {
        "status": "success", 
        "games": [
            {
                "id": "mock_nfl_1",
                "home_team": "Kansas City Chiefs",
                "away_team": "Buffalo Bills", 
                "start_time": "2025-01-12T21:00:00Z",
                "status": "scheduled"
            }
        ],
        "message": "Mock data - Sports pipeline not fully configured"
    }

@app.get("/api/odds/nfl")
async def get_nfl_odds():
    """Get NFL odds"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            # Try to use real odds service
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("americanfootball_nfl")
                return {"status": "success", "odds": games}
        except Exception as e:
            logger.error(f"Error fetching NFL odds: {e}")
            # Fall through to mock data
    
    # Return mock data
    return {
        "status": "success",
        "odds": [
            {
                "id": "mock_odds_1",
                "sport_title": "NFL",
                "home_team": "Kansas City Chiefs",
                "away_team": "Buffalo Bills",
                "bookmakers": [
                    {
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "h2h", 
                                "outcomes": [
                                    {"name": "Kansas City Chiefs", "price": -110},
                                    {"name": "Buffalo Bills", "price": -110}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": "Mock data - Odds API not configured"
    }

@app.get("/api/odds/popular")
async def get_popular_sports_odds():
    """Get odds for popular sports (NFL, NBA, MLB, NHL)"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            # Try to use real odds service
            from app.services.odds_api_service import get_popular_sports_odds
            games = await get_popular_sports_odds()
            return {"status": "success", "data": games}
        except Exception as e:
            logger.error(f"Error fetching popular sports odds: {e}")
            # Fall through to mock data
    
    # Return mock data for production/when services unavailable
    return {
        "status": "success",
        "data": [
            {
                "id": "mock_game_1",
                "sport_title": "NFL",
                "home_team": "Kansas City Chiefs", 
                "away_team": "Buffalo Bills",
                "commence_time": "2025-01-12T21:00:00Z",
                "bookmakers": [
                    {
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Kansas City Chiefs", "price": -110},
                                    {"name": "Buffalo Bills", "price": -110}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "id": "mock_game_2", 
                "sport_title": "NBA",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "commence_time": "2025-01-12T22:00:00Z",
                "bookmakers": [
                    {
                        "title": "FanDuel",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Los Angeles Lakers", "price": 105},
                                    {"name": "Boston Celtics", "price": -125}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": f"Mock data - Running in {settings.ENVIRONMENT} mode"
    }

# Additional odds endpoints for specific sports
@app.options("/api/odds/americanfootball_nfl")
async def options_nfl_odds():
    """Handle CORS preflight for NFL odds endpoint"""
    return {}

@app.get("/api/odds/americanfootball_nfl")
async def get_nfl_odds_direct():
    """Get NFL odds (direct API endpoint)"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                odds = await service.get_odds("americanfootball_nfl")
                return {"status": "success", "odds": odds}
        except Exception as e:
            logger.error(f"Error fetching NFL odds: {e}")
    
    # Mock NFL odds
    return {
        "status": "success",
        "odds": [
            {
                "id": "mock_nfl_odds_1",
                "sport_title": "NFL",
                "home_team": "Kansas City Chiefs",
                "away_team": "Buffalo Bills",
                "commence_time": "2025-01-12T21:00:00Z",
                "bookmakers": [
                    {
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Kansas City Chiefs", "price": -125},
                                    {"name": "Buffalo Bills", "price": 105}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": "Mock NFL odds - Odds API not configured"
    }

@app.options("/api/odds/basketball_nba")
async def options_nba_odds():
    """Handle CORS preflight for NBA odds endpoint"""
    return {}

@app.get("/api/odds/basketball_nba")
async def get_nba_odds():
    """Get NBA odds"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                odds = await service.get_odds("basketball_nba")
                return {"status": "success", "odds": odds}
        except Exception as e:
            logger.error(f"Error fetching NBA odds: {e}")
    
    # Mock NBA odds
    return {
        "status": "success",
        "odds": [
            {
                "id": "mock_nba_odds_1",
                "sport_title": "NBA",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "commence_time": "2025-01-12T22:00:00Z",
                "bookmakers": [
                    {
                        "title": "FanDuel",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Los Angeles Lakers", "price": 110},
                                    {"name": "Boston Celtics", "price": -130}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": "Mock NBA odds - Odds API not configured"
    }

@app.options("/api/odds/baseball_mlb")
async def options_mlb_odds():
    """Handle CORS preflight for MLB odds endpoint"""
    return {}

@app.get("/api/odds/baseball_mlb")
async def get_mlb_odds():
    """Get MLB odds"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                odds = await service.get_odds("baseball_mlb")
                return {"status": "success", "odds": odds}
        except Exception as e:
            logger.error(f"Error fetching MLB odds: {e}")
    
    # Mock MLB odds
    return {
        "status": "success",
        "odds": [
            {
                "id": "mock_mlb_odds_1",
                "sport_title": "MLB",
                "home_team": "New York Yankees",
                "away_team": "Boston Red Sox",
                "commence_time": "2025-04-15T19:00:00Z",
                "bookmakers": [
                    {
                        "title": "BetMGM",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "New York Yankees", "price": -145},
                                    {"name": "Boston Red Sox", "price": 125}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": "Mock MLB odds - Odds API not configured"
    }

@app.options("/api/odds/icehockey_nhl")
async def options_nhl_odds():
    """Handle CORS preflight for NHL odds endpoint"""
    return {}

@app.get("/api/odds/icehockey_nhl")
async def get_nhl_odds():
    """Get NHL odds"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                odds = await service.get_odds("icehockey_nhl")
                return {"status": "success", "odds": odds}
        except Exception as e:
            logger.error(f"Error fetching NHL odds: {e}")
    
    # Mock NHL odds
    return {
        "status": "success",
        "odds": [
            {
                "id": "mock_nhl_odds_1",
                "sport_title": "NHL",
                "home_team": "Toronto Maple Leafs",
                "away_team": "Montreal Canadiens",
                "commence_time": "2025-01-15T20:00:00Z",
                "bookmakers": [
                    {
                        "title": "Bet365",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Toronto Maple Leafs", "price": -115},
                                    {"name": "Montreal Canadiens", "price": -105}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": "Mock NHL odds - Odds API not configured"
    }

@app.options("/api/odds/hockey")
async def options_hockey_odds():
    """Handle CORS preflight for hockey odds endpoint (alias for NHL)"""
    return {}

@app.get("/api/odds/hockey")
async def get_hockey_odds():
    """Get hockey odds (alias for NHL)"""
    # This is an alias that redirects to NHL odds
    return await get_nhl_odds()

# AI Chat endpoints
@app.post("/api/chat/message")
async def send_chat_message(request: ChatRequest):
    """Send a message to AI chat service"""
    if is_service_available("ai_chat_service"):
        try:
            ai_chat = get_service("ai_chat_service")
            response = await ai_chat.send_message(
                request.message, 
                request.conversation_history or []
            )
            return {"status": "success", "response": response}
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            # Fall through to mock response
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "response": {
            "role": "assistant",
            "content": f"I'm currently in {settings.ENVIRONMENT} mode with limited AI capabilities. Here's some general sports betting advice: Always bet responsibly and never wager more than you can afford to lose!",
            "timestamp": datetime.utcnow().isoformat()
        },
        "message": "Mock response - AI chat service not fully configured"
    }

@app.get("/api/chat/suggestions")
async def get_chat_suggestions():
    """Get chat suggestions for the user"""
    return {
        "status": "success",
        "suggestions": [
            "Show me the latest NFL odds",
            "What's your prediction for the Chiefs game?", 
            "Give me fantasy football advice for this week",
            "What should I know about tonight's matchup?"
        ]
    }

# YetAI Bets endpoints
@app.options("/api/yetai-bets")
async def options_yetai_bets():
    """Handle CORS preflight for YetAI bets endpoint"""
    return {}

@app.get("/api/yetai-bets")
async def get_yetai_bets():
    """Get YetAI bets for user"""
    if is_service_available("yetai_bets_service"):
        try:
            yetai_service = get_service("yetai_bets_service")
            bets = await yetai_service.get_active_bets()
            return {"status": "success", "bets": bets}
        except Exception as e:
            logger.error(f"Error fetching YetAI bets: {e}")
    
    # Return empty list when service unavailable
    return {
        "status": "success",
        "bets": [],
        "message": "YetAI bets service unavailable"
    }

# Betting endpoints
@app.options("/api/bets/place")
async def options_place_bet():
    """Handle CORS preflight for place bet endpoint"""
    return {}

@app.post("/api/bets/place")
async def place_bet(bet_data: dict):
    """Place a single bet"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.place_bet(bet_data)
            return {"status": "success", "bet": result}
        except Exception as e:
            logger.error(f"Error placing bet: {e}")
            return {
                "status": "error",
                "message": "Failed to place bet",
                "error": str(e)
            }
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "bet": {
            "id": "mock_bet_123",
            "bet_type": bet_data.get("bet_type", "moneyline"),
            "selection": bet_data.get("selection", "Unknown Team"),
            "odds": bet_data.get("odds", -110),
            "amount": bet_data.get("amount", 100),
            "potential_payout": bet_data.get("amount", 100) * 1.91,  # Rough calculation
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        },
        "message": "Mock bet placed - Bet service unavailable"
    }

@app.options("/api/bets/parlay")
async def options_place_parlay():
    """Handle CORS preflight for parlay bet endpoint"""
    return {}

@app.post("/api/bets/parlay")
async def place_parlay_bet(parlay_data: dict):
    """Place a parlay bet"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.place_parlay_bet(parlay_data)
            return {"status": "success", "parlay": result}
        except Exception as e:
            logger.error(f"Error placing parlay bet: {e}")
            return {
                "status": "error",
                "message": "Failed to place parlay bet",
                "error": str(e)
            }
    
    # Mock response when service unavailable
    legs = parlay_data.get("legs", [])
    return {
        "status": "success",
        "parlay": {
            "id": "mock_parlay_123",
            "amount": parlay_data.get("amount", 50),
            "legs": legs,
            "total_odds": 350,  # Mock combined odds
            "potential_payout": parlay_data.get("amount", 50) * 3.5,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        },
        "message": "Mock parlay placed - Bet service unavailable"
    }

@app.options("/api/bets/parlays")
async def options_get_parlays():
    """Handle CORS preflight for get parlays endpoint"""
    return {}

@app.get("/api/bets/parlays")
async def get_user_parlays():
    """Get user's parlay bets"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            parlays = await bet_service.get_user_parlays()
            return {"status": "success", "parlays": parlays}
        except Exception as e:
            logger.error(f"Error fetching parlays: {e}")
    
    return {
        "status": "success",
        "parlays": [],
        "message": "Bet service unavailable"
    }

@app.get("/api/bets/parlay/{parlay_id}")
async def get_parlay_details(parlay_id: str):
    """Get specific parlay details"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            parlay = await bet_service.get_parlay_by_id(parlay_id)
            return {"status": "success", "parlay": parlay}
        except Exception as e:
            logger.error(f"Error fetching parlay {parlay_id}: {e}")
    
    return {
        "status": "success",
        "parlay": {
            "id": parlay_id,
            "amount": 50,
            "legs": [],
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        },
        "message": "Mock parlay data - Bet service unavailable"
    }

@app.options("/api/bets/stats")
async def options_bet_stats():
    """Handle CORS preflight for bet stats endpoint"""
    return {}

@app.get("/api/bets/stats")
async def get_bet_stats():
    """Get betting statistics for user"""
    if is_service_available("betting_analytics_service"):
        try:
            analytics_service = get_service("betting_analytics_service")
            stats = await analytics_service.get_user_stats()
            return {"status": "success", "stats": stats}
        except Exception as e:
            logger.error(f"Error fetching bet stats: {e}")
    elif is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            stats = await bet_service.get_betting_stats()
            return {"status": "success", "stats": stats}
        except Exception as e:
            logger.error(f"Error fetching bet stats from bet service: {e}")
    
    # Mock stats when service unavailable
    return {
        "status": "success",
        "stats": {
            "total_bets": 0,
            "total_wagered": 0,
            "total_won": 0,
            "win_rate": 0,
            "profit_loss": 0,
            "average_odds": -110,
            "favorite_sport": "NFL",
            "bet_types": {
                "moneyline": 0,
                "spread": 0,
                "over_under": 0,
                "parlay": 0
            }
        },
        "message": "Mock stats - Analytics service unavailable"
    }

@app.options("/api/bets/share")
async def options_share_bet():
    """Handle CORS preflight for share bet endpoint"""
    return {}

@app.post("/api/bets/share")
async def share_bet(share_data: dict):
    """Share a bet with other users"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.share_bet(share_data)
            return {"status": "success", "shared_bet": result}
        except Exception as e:
            logger.error(f"Error sharing bet: {e}")
            return {
                "status": "error",
                "message": "Failed to share bet",
                "error": str(e)
            }
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "shared_bet": {
            "share_id": "mock_share_123",
            "bet_id": share_data.get("bet_id", "unknown"),
            "message": share_data.get("message", "Check out my bet!"),
            "shared_at": datetime.utcnow().isoformat(),
            "expires_at": datetime.utcnow().isoformat()
        },
        "message": "Mock share created - Bet service unavailable"
    }

@app.options("/api/bets/shared")
async def options_get_shared_bets():
    """Handle CORS preflight for get shared bets endpoint"""
    return {}

@app.get("/api/bets/shared")
async def get_shared_bets():
    """Get shared bets from other users"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            shared_bets = await bet_service.get_shared_bets()
            return {"status": "success", "shared_bets": shared_bets}
        except Exception as e:
            logger.error(f"Error fetching shared bets: {e}")
    
    return {
        "status": "success",
        "shared_bets": [],
        "message": "Bet service unavailable"
    }

@app.options("/api/bets/shared/{share_id}")
async def options_delete_shared_bet(share_id: str):
    """Handle CORS preflight for delete shared bet endpoint"""
    return {}

@app.delete("/api/bets/shared/{share_id}")
async def delete_shared_bet(share_id: str):
    """Delete a shared bet"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.delete_shared_bet(share_id)
            return {"status": "success", "message": "Shared bet deleted"}
        except Exception as e:
            logger.error(f"Error deleting shared bet {share_id}: {e}")
            return {
                "status": "error",
                "message": "Failed to delete shared bet",
                "error": str(e)
            }
    
    return {
        "status": "success",
        "message": f"Mock deletion of shared bet {share_id} - Bet service unavailable"
    }

@app.options("/api/bets/{bet_id}")
async def options_cancel_bet(bet_id: str):
    """Handle CORS preflight for cancel bet endpoint"""
    return {}

@app.delete("/api/bets/{bet_id}")
async def cancel_bet(bet_id: str):
    """Cancel/delete a bet"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.cancel_bet(bet_id)
            return {"status": "success", "message": "Bet cancelled"}
        except Exception as e:
            logger.error(f"Error cancelling bet {bet_id}: {e}")
            return {
                "status": "error",
                "message": "Failed to cancel bet",
                "error": str(e)
            }
    
    return {
        "status": "success",
        "message": f"Mock cancellation of bet {bet_id} - Bet service unavailable"
    }

@app.options("/api/bets/simulate")
async def options_simulate_bet():
    """Handle CORS preflight for simulate bet endpoint"""
    return {}

@app.post("/api/bets/simulate")
async def simulate_bet_results(simulation_data: dict = None):
    """Simulate bet results for testing"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.simulate_bet_results(simulation_data or {})
            return {"status": "success", "simulation": result}
        except Exception as e:
            logger.error(f"Error simulating bet: {e}")
            return {
                "status": "error",
                "message": "Failed to simulate bet",
                "error": str(e)
            }
    
    # Mock simulation when service unavailable
    return {
        "status": "success",
        "simulation": {
            "bet_id": "mock_sim_123",
            "result": "win",
            "payout": 191.0,
            "profit": 91.0,
            "simulated_at": datetime.utcnow().isoformat()
        },
        "message": "Mock simulation - Bet service unavailable"
    }

@app.options("/api/bets/history")
async def options_bet_history():
    """Handle CORS preflight for bet history endpoint"""
    return {}

@app.post("/api/bets/history")
async def get_bet_history(query: dict):
    """Get user bet history"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            history = await bet_service.get_bet_history(**query)
            return {"status": "success", "history": history}
        except Exception as e:
            logger.error(f"Error fetching bet history: {e}")
    
    return {
        "status": "success",
        "history": [],
        "message": "Bet service unavailable"
    }

# Fantasy endpoints  
@app.options("/api/fantasy/accounts")
async def options_fantasy_accounts():
    """Handle CORS preflight for fantasy accounts endpoint"""
    return {}

@app.get("/api/fantasy/accounts")
async def get_fantasy_accounts():
    """Get user's fantasy accounts"""
    if is_service_available("fantasy_pipeline") or is_service_available("real_fantasy_pipeline"):
        try:
            # Try real fantasy pipeline first, then fallback to mock
            fantasy_service = get_service("real_fantasy_pipeline") or get_service("fantasy_pipeline")
            accounts = await fantasy_service.get_user_accounts()
            return {"status": "success", "accounts": accounts}
        except Exception as e:
            logger.error(f"Error fetching fantasy accounts: {e}")
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "accounts": [],
        "message": "Fantasy service unavailable - Mock data"
    }

@app.options("/api/fantasy/leagues")
async def options_fantasy_leagues():
    """Handle CORS preflight for fantasy leagues endpoint"""
    return {}

@app.get("/api/fantasy/leagues")
async def get_fantasy_leagues():
    """Get user's fantasy leagues"""
    if is_service_available("fantasy_pipeline") or is_service_available("real_fantasy_pipeline"):
        try:
            fantasy_service = get_service("real_fantasy_pipeline") or get_service("fantasy_pipeline")
            leagues = await fantasy_service.get_user_leagues()
            return {"status": "success", "leagues": leagues}
        except Exception as e:
            logger.error(f"Error fetching fantasy leagues: {e}")
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "leagues": [],
        "message": "Fantasy service unavailable - Mock data"
    }

@app.options("/api/fantasy/connect")
async def options_fantasy_connect():
    """Handle CORS preflight for fantasy connect endpoint"""
    return {}

@app.post("/api/fantasy/connect")
async def connect_fantasy_platform(connection_data: dict):
    """Connect to a fantasy platform (Sleeper, ESPN, etc.)"""
    if is_service_available("fantasy_pipeline") or is_service_available("real_fantasy_pipeline"):
        try:
            fantasy_service = get_service("real_fantasy_pipeline") or get_service("fantasy_pipeline")
            result = await fantasy_service.connect_platform(
                platform=connection_data.get("platform"),
                credentials=connection_data.get("credentials", {})
            )
            return {"status": "success", "connection": result}
        except Exception as e:
            logger.error(f"Error connecting to fantasy platform: {e}")
            return {
                "status": "error",
                "message": "Failed to connect to fantasy platform",
                "error": str(e)
            }
    
    # Mock response when service unavailable
    platform = connection_data.get("platform", "unknown")
    return {
        "status": "success",
        "connection": {
            "platform": platform,
            "status": "connected",
            "connected_at": datetime.utcnow().isoformat(),
            "username": connection_data.get("credentials", {}).get("username", "mock_user")
        },
        "message": f"Mock connection to {platform} - Fantasy service unavailable"
    }

@app.options("/api/fantasy/roster/{league_id}")
async def options_fantasy_roster(league_id: str):
    """Handle CORS preflight for fantasy roster endpoint"""
    return {}

@app.get("/api/fantasy/roster/{league_id}")
async def get_fantasy_roster(league_id: str):
    """Get fantasy roster for a specific league"""
    if is_service_available("fantasy_pipeline") or is_service_available("real_fantasy_pipeline"):
        try:
            fantasy_service = get_service("real_fantasy_pipeline") or get_service("fantasy_pipeline")
            roster = await fantasy_service.get_roster(league_id)
            return {"status": "success", "roster": roster}
        except Exception as e:
            logger.error(f"Error fetching fantasy roster for league {league_id}: {e}")
    
    # Mock roster when service unavailable
    return {
        "status": "success",
        "roster": {
            "league_id": league_id,
            "team_name": "Mock Team",
            "players": [],
            "starters": [],
            "bench": [],
            "total_points": 0
        },
        "message": f"Mock roster for league {league_id} - Fantasy service unavailable"
    }

@app.options("/api/fantasy/projections")
async def options_fantasy_projections():
    """Handle CORS preflight for fantasy projections endpoint"""
    return {}

@app.get("/api/fantasy/projections")
async def get_fantasy_projections():
    """Get fantasy projections"""
    if is_service_available("fantasy_pipeline"):
        try:
            fantasy_service = get_service("fantasy_pipeline")
            projections = await fantasy_service.get_projections()
            return {"status": "success", "projections": projections}
        except Exception as e:
            logger.error(f"Error fetching fantasy projections: {e}")
    
    return {
        "status": "success",
        "projections": [],
        "message": "Fantasy pipeline unavailable"
    }

# Live betting endpoints
@app.options("/api/live-bets/markets")
async def options_live_markets():
    """Handle CORS preflight for live markets endpoint"""
    return {}

@app.get("/api/live-bets/markets")
async def get_live_markets():
    """Get live betting markets"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            markets = await bet_service.get_live_markets()
            return {"status": "success", "markets": markets}
        except Exception as e:
            logger.error(f"Error fetching live markets: {e}")
    
    return {
        "status": "success",
        "markets": [],
        "message": "Bet service unavailable"
    }

@app.options("/api/live-bets/active")
async def options_active_live_bets():
    """Handle CORS preflight for active live bets endpoint"""
    return {}

@app.get("/api/live-bets/active")
async def get_active_live_bets():
    """Get active live bets"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            active_bets = await bet_service.get_active_live_bets()
            return {"status": "success", "active_bets": active_bets}
        except Exception as e:
            logger.error(f"Error fetching active live bets: {e}")
    
    return {
        "status": "success",
        "active_bets": [],
        "message": "Bet service unavailable"
    }

# Parlay-specific endpoints
@app.options("/api/parlays/markets")
async def options_parlay_markets():
    """Handle CORS preflight for parlay markets endpoint"""
    return {}

@app.get("/api/parlays/markets")
async def get_parlay_markets(sport: str = None):
    """Get parlay markets, optionally filtered by sport"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            markets = await bet_service.get_parlay_markets(sport=sport)
            return {"status": "success", "markets": markets}
        except Exception as e:
            logger.error(f"Error fetching parlay markets: {e}")
    
    # Mock parlay markets
    base_markets = [
        {
            "sport": "NFL",
            "markets": [
                {"type": "moneyline", "description": "Team to win"},
                {"type": "spread", "description": "Point spread"},
                {"type": "total", "description": "Over/Under"},
                {"type": "player_props", "description": "Player prop bets"}
            ]
        },
        {
            "sport": "NBA",
            "markets": [
                {"type": "moneyline", "description": "Team to win"},
                {"type": "spread", "description": "Point spread"},
                {"type": "total", "description": "Over/Under"},
                {"type": "player_props", "description": "Player prop bets"}
            ]
        },
        {
            "sport": "NHL",
            "markets": [
                {"type": "moneyline", "description": "Team to win"},
                {"type": "puck_line", "description": "Puck line"},
                {"type": "total", "description": "Over/Under goals"}
            ]
        },
        {
            "sport": "MLB",
            "markets": [
                {"type": "moneyline", "description": "Team to win"},
                {"type": "run_line", "description": "Run line"},
                {"type": "total", "description": "Over/Under runs"}
            ]
        }
    ]
    
    # Filter by sport if specified
    if sport:
        filtered_markets = [m for m in base_markets if m["sport"].lower() == sport.lower() or sport.lower() in m["sport"].lower()]
        markets = filtered_markets if filtered_markets else base_markets
    else:
        markets = base_markets
    
    return {
        "status": "success",
        "markets": markets,
        "message": "Mock parlay markets - Bet service unavailable"
    }

@app.options("/api/parlays/popular")
async def options_popular_parlays():
    """Handle CORS preflight for popular parlays endpoint"""
    return {}

@app.get("/api/parlays/popular")
async def get_popular_parlays():
    """Get popular parlay combinations"""
    if is_service_available("betting_analytics_service"):
        try:
            analytics_service = get_service("betting_analytics_service")
            popular = await analytics_service.get_popular_parlays()
            return {"status": "success", "parlays": popular}
        except Exception as e:
            logger.error(f"Error fetching popular parlays: {e}")
    elif is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            popular = await bet_service.get_popular_parlays()
            return {"status": "success", "parlays": popular}
        except Exception as e:
            logger.error(f"Error fetching popular parlays from bet service: {e}")
    
    # Mock popular parlays
    return {
        "status": "success",
        "parlays": [
            {
                "id": "popular_parlay_1",
                "name": "NFL Sunday Special",
                "legs": [
                    {"selection": "Chiefs ML", "odds": -150},
                    {"selection": "Bills -3.5", "odds": -110},
                    {"selection": "Over 45.5 points", "odds": -105}
                ],
                "combined_odds": 450,
                "popularity_score": 85,
                "recent_wins": 7,
                "recent_attempts": 10
            },
            {
                "id": "popular_parlay_2",
                "name": "NBA Triple Threat",
                "legs": [
                    {"selection": "Lakers ML", "odds": -120},
                    {"selection": "Celtics -2.5", "odds": -110},
                    {"selection": "LeBron Over 25.5 points", "odds": -115}
                ],
                "combined_odds": 380,
                "popularity_score": 78,
                "recent_wins": 6,
                "recent_attempts": 12
            }
        ],
        "message": "Mock popular parlays - Analytics service unavailable"
    }

# Admin endpoints
@app.options("/api/admin/yetai-bets/{bet_id}")
async def options_admin_delete_yetai_bet(bet_id: str):
    """Handle CORS preflight for admin YetAI bet deletion endpoint"""
    return {}

@app.delete("/api/admin/yetai-bets/{bet_id}")
async def admin_delete_yetai_bet(bet_id: str):
    """Admin endpoint to delete a YetAI bet"""
    # This would typically require admin authentication
    if is_service_available("yetai_bets_service"):
        try:
            yetai_service = get_service("yetai_bets_service")
            result = await yetai_service.admin_delete_bet(bet_id)
            return {
                "status": "success",
                "message": f"YetAI bet {bet_id} deleted by admin",
                "deleted_bet": result
            }
        except Exception as e:
            logger.error(f"Error deleting YetAI bet {bet_id}: {e}")
            return {
                "status": "error",
                "message": "Failed to delete YetAI bet",
                "error": str(e)
            }
    
    # Mock admin deletion when service unavailable
    return {
        "status": "success",
        "message": f"Mock admin deletion of YetAI bet {bet_id} - YetAI bets service unavailable",
        "deleted_bet": {
            "id": bet_id,
            "deleted_at": datetime.utcnow().isoformat(),
            "deleted_by": "admin"
        }
    }

# Profile endpoints
@app.options("/api/profile/sports")
async def options_profile_sports():
    """Handle CORS preflight for profile sports endpoint"""
    return {}

@app.get("/api/profile/sports")
async def get_user_sports_preferences():
    """Get user's sports preferences"""
    if is_service_available("auth_service"):
        try:
            auth_service = get_service("auth_service")
            preferences = await auth_service.get_user_preferences()
            return {
                "status": "success", 
                "sports_preferences": preferences.get("preferred_sports", [])
            }
        except Exception as e:
            logger.error(f"Error fetching sports preferences: {e}")
    
    # Mock sports preferences
    return {
        "status": "success",
        "sports_preferences": [
            {
                "sport": "NFL",
                "favorite_teams": ["Kansas City Chiefs", "Buffalo Bills"],
                "interest_level": "high",
                "notification_enabled": True
            },
            {
                "sport": "NBA",
                "favorite_teams": ["Los Angeles Lakers", "Boston Celtics"],
                "interest_level": "medium",
                "notification_enabled": True
            },
            {
                "sport": "NHL",
                "favorite_teams": ["Toronto Maple Leafs"],
                "interest_level": "low",
                "notification_enabled": False
            }
        ],
        "message": "Mock sports preferences - Auth service unavailable"
    }

@app.options("/api/profile/status")
async def options_profile_status():
    """Handle CORS preflight for profile status endpoint"""
    return {}

@app.get("/api/profile/status")
async def get_user_profile_status():
    """Get user's profile status and statistics"""
    if is_service_available("auth_service"):
        try:
            auth_service = get_service("auth_service")
            profile = await auth_service.get_user_profile()
            
            # Get betting stats if available
            betting_stats = {}
            if is_service_available("betting_analytics_service"):
                analytics_service = get_service("betting_analytics_service")
                betting_stats = await analytics_service.get_user_stats()
            elif is_service_available("bet_service"):
                bet_service = get_service("bet_service")
                betting_stats = await bet_service.get_betting_stats()
            
            return {
                "status": "success",
                "profile": {
                    "user_id": profile.get("id"),
                    "username": profile.get("username"),
                    "email": profile.get("email"),
                    "joined_date": profile.get("created_at"),
                    "betting_stats": betting_stats,
                    "account_status": "active",
                    "verification_status": "verified"
                }
            }
        except Exception as e:
            logger.error(f"Error fetching profile status: {e}")
    
    # Mock profile status
    return {
        "status": "success",
        "profile": {
            "user_id": "mock_user_123",
            "username": "demo_user",
            "email": "demo@yetai.com",
            "joined_date": "2025-01-01T00:00:00Z",
            "betting_stats": {
                "total_bets": 0,
                "total_wagered": 0,
                "total_won": 0,
                "win_rate": 0,
                "profit_loss": 0
            },
            "account_status": "active",
            "verification_status": "pending"
        },
        "message": "Mock profile status - Auth service unavailable"
    }

# Test endpoint for database connectivity
@app.get("/test-db")
async def test_database():
    """Test database connection with detailed debugging"""
    debug_info = {
        "environment": settings.ENVIRONMENT,
        "database_url": settings.DATABASE_URL[:50] + "..." if len(settings.DATABASE_URL) > 50 else settings.DATABASE_URL,
        "service_available": is_service_available("database")
    }
    
    if not is_service_available("database"):
        return {
            "status": "unavailable",
            "message": "Database service not loaded",
            "debug": debug_info
        }
    
    try:
        database_service = get_service("database")
        debug_info["service_loaded"] = database_service is not None
        
        if database_service and database_service.get("check_db_connection"):
            debug_info["check_function_available"] = True
            connected = database_service["check_db_connection"]()
            debug_info["connection_result"] = connected
            
            return {
                "status": "connected" if connected else "disconnected",
                "message": "Database connection successful" if connected else "Database connection failed",
                "debug": debug_info
            }
        else:
            debug_info["check_function_available"] = False
            return {
                "status": "error",
                "message": "Database check function not available",
                "debug": debug_info
            }
    except Exception as e:
        debug_info["exception"] = str(e)
        debug_info["exception_type"] = str(type(e))
        return {
            "status": "error", 
            "message": f"Database test failed: {str(e)}",
            "debug": debug_info
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Starting server on port {port} - {settings.ENVIRONMENT.upper()} mode")
    uvicorn.run(app, host="0.0.0.0", port=port)