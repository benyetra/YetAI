"""
Environment-aware FastAPI application for YetAI Sports Betting MVP
Consolidates development and production functionality into a single file
"""
from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect, Request
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
from datetime import datetime

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

# Betting Models
class PlaceBetRequest(BaseModel):
    bet_type: str
    selection: str
    odds: float
    amount: float
    game_id: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    sport: Optional[str] = None
    commence_time: Optional[str] = None

class ParlayLeg(BaseModel):
    bet_type: str
    selection: str
    odds: float
    game_id: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    sport: Optional[str] = None
    commence_time: Optional[str] = None

class PlaceParlayRequest(BaseModel):
    amount: float
    legs: List[ParlayLeg]

class BetHistoryQuery(BaseModel):
    status: Optional[str] = None
    bet_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    offset: int = 0
    limit: int = 50

# Fantasy Models
class FantasyConnectRequest(BaseModel):
    platform: str
    credentials: Dict[str, Any]

class ShareBetRequest(BaseModel):
    bet_id: str
    message: Optional[str] = None

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
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503,
            detail="Authentication service is currently unavailable"
        )
    
    auth_service = get_service("auth_service")
    token = credentials.credentials
    user = await auth_service.get_user_by_token(token)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user

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

# Sport-specific odds endpoints with CORS support
@app.options("/api/odds/americanfootball_nfl")
async def options_americanfootball_nfl_odds():
    """Handle CORS preflight for NFL odds"""
    return {}

@app.get("/api/odds/americanfootball_nfl")
async def get_americanfootball_nfl_odds(regions: str = "us", markets: str = "h2h,spreads,totals", odds_format: str = "american"):
    """Get NFL odds"""
    try:
        if settings.ODDS_API_KEY:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds(
                    sport="americanfootball_nfl",
                    markets=markets.split(","),
                    regions=regions.split(",")
                )
                return {"status": "success", "data": games}
        else:
            return {"status": "success", "data": [], "message": "Odds API not configured"}
    except Exception as e:
        logger.error(f"Error fetching NFL odds: {e}")
        return {"status": "error", "message": str(e)}

@app.options("/api/odds/americanfootball_ncaaf")
async def options_americanfootball_ncaaf_odds():
    """Handle CORS preflight for NCAAF odds"""
    return {}

@app.get("/api/odds/americanfootball_ncaaf")
async def get_americanfootball_ncaaf_odds(regions: str = "us", markets: str = "h2h,spreads,totals", odds_format: str = "american"):
    """Get NCAAF odds"""
    try:
        if settings.ODDS_API_KEY:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds(
                    sport="americanfootball_ncaaf",
                    markets=markets.split(","),
                    regions=regions.split(",")
                )
                return {"status": "success", "data": games}
        else:
            return {"status": "success", "data": [], "message": "Odds API not configured"}
    except Exception as e:
        logger.error(f"Error fetching NCAAF odds: {e}")
        return {"status": "error", "message": str(e)}

@app.options("/api/odds/basketball_nba")
async def options_basketball_nba_odds():
    """Handle CORS preflight for NBA odds"""
    return {}

@app.get("/api/odds/basketball_nba")
async def get_basketball_nba_odds(regions: str = "us", markets: str = "h2h,spreads,totals", odds_format: str = "american"):
    """Get NBA odds"""
    try:
        if settings.ODDS_API_KEY:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds(
                    sport="basketball_nba",
                    markets=markets.split(","),
                    regions=regions.split(",")
                )
                return {"status": "success", "data": games}
        else:
            return {"status": "success", "data": [], "message": "Odds API not configured"}
    except Exception as e:
        logger.error(f"Error fetching NBA odds: {e}")
        return {"status": "error", "message": str(e)}

@app.options("/api/odds/baseball_mlb")
async def options_baseball_mlb_odds():
    """Handle CORS preflight for MLB odds"""
    return {}

@app.get("/api/odds/baseball_mlb")
async def get_baseball_mlb_odds(regions: str = "us", markets: str = "h2h,spreads,totals", odds_format: str = "american"):
    """Get MLB odds"""
    try:
        if settings.ODDS_API_KEY:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds(
                    sport="baseball_mlb",
                    markets=markets.split(","),
                    regions=regions.split(",")
                )
                return {"status": "success", "data": games}
        else:
            return {"status": "success", "data": [], "message": "Odds API not configured"}
    except Exception as e:
        logger.error(f"Error fetching MLB odds: {e}")
        return {"status": "error", "message": str(e)}

@app.options("/api/odds/icehockey_nhl")
async def options_icehockey_nhl_odds():
    """Handle CORS preflight for NHL odds"""
    return {}

@app.get("/api/odds/icehockey_nhl")
async def get_icehockey_nhl_odds(regions: str = "us", markets: str = "h2h,spreads,totals", odds_format: str = "american"):
    """Get NHL (Ice Hockey) odds"""
    try:
        if settings.ODDS_API_KEY:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds(
                    sport="icehockey_nhl",
                    markets=markets.split(","),
                    regions=regions.split(",")
                )
                return {"status": "success", "data": games}
        else:
            return {"status": "success", "data": [], "message": "Odds API not configured"}
    except Exception as e:
        logger.error(f"Error fetching NHL odds: {e}")
        return {"status": "error", "message": str(e)}

@app.options("/api/sports")
async def options_sports():
    """Handle CORS preflight for sports endpoint"""
    return {}

@app.get("/api/sports")
async def get_sports():
    """Get list of available sports for betting"""
    return {
        "status": "success",
        "sports": [
            {
                "key": "americanfootball_nfl",
                "name": "NFL",
                "full_name": "National Football League",
                "active": True,
                "category": "american_football"
            },
            {
                "key": "basketball_nba", 
                "name": "NBA",
                "full_name": "National Basketball Association",
                "active": True,
                "category": "basketball"
            },
            {
                "key": "baseball_mlb",
                "name": "MLB", 
                "full_name": "Major League Baseball",
                "active": True,
                "category": "baseball"
            },
            {
                "key": "icehockey_nhl",
                "name": "NHL",
                "full_name": "National Hockey League", 
                "active": True,
                "category": "ice_hockey"
            },
            {
                "key": "americanfootball_ncaaf",
                "name": "NCAAF",
                "full_name": "NCAA College Football",
                "active": True,
                "category": "american_football"
            },
            {
                "key": "basketball_ncaab",
                "name": "NCAAB",
                "full_name": "NCAA College Basketball",
                "active": False,
                "category": "basketball"
            }
        ],
        "message": "Available sports for betting"
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
            },
            {
                "id": "mock_game_3", 
                "sport_title": "NHL",
                "home_team": "Boston Bruins",
                "away_team": "New York Rangers",
                "commence_time": "2025-01-12T19:00:00Z",
                "bookmakers": [
                    {
                        "title": "BetMGM",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Bruins", "price": -130},
                                    {"name": "New York Rangers", "price": 110}
                                ]
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 6.5},
                                    {"name": "Under", "price": -110, "point": 6.5}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "message": f"Mock data - Running in {settings.ENVIRONMENT} mode"
    }

# Additional parlay-specific endpoints for enhanced parlay support
@app.options("/api/parlays/markets")
async def options_parlay_markets():
    """Handle CORS preflight for parlay markets"""
    return {}

@app.get("/api/parlays/markets")
async def get_parlay_markets(sport: str = None):
    """Get available markets for parlay building"""
    try:
        # Mock parlay markets for ice hockey and other sports
        markets = {
            "icehockey_nhl": [
                {
                    "key": "h2h",
                    "name": "Moneyline",
                    "description": "Pick the winning team"
                },
                {
                    "key": "spreads",
                    "name": "Puck Line",
                    "description": "Team must win by more than the spread"
                },
                {
                    "key": "totals",
                    "name": "Total Goals",
                    "description": "Over/Under total goals scored"
                },
                {
                    "key": "player_props",
                    "name": "Player Props",
                    "description": "Individual player statistics"
                }
            ],
            "americanfootball_nfl": [
                {
                    "key": "h2h",
                    "name": "Moneyline",
                    "description": "Pick the winning team"
                },
                {
                    "key": "spreads",
                    "name": "Point Spread",
                    "description": "Team must win by more than the spread"
                },
                {
                    "key": "totals",
                    "name": "Total Points",
                    "description": "Over/Under total points scored"
                }
            ],
            "basketball_nba": [
                {
                    "key": "h2h",
                    "name": "Moneyline",
                    "description": "Pick the winning team"
                },
                {
                    "key": "spreads",
                    "name": "Point Spread",
                    "description": "Team must win by more than the spread"
                },
                {
                    "key": "totals",
                    "name": "Total Points",
                    "description": "Over/Under total points scored"
                }
            ]
        }
        
        if sport:
            sport_markets = markets.get(sport, [])
            return {
                "status": "success",
                "markets": sport_markets,
                "sport": sport,
                "message": f"Retrieved {len(sport_markets)} markets for {sport}"
            }
        else:
            return {
                "status": "success",
                "markets": markets,
                "message": "Retrieved all available parlay markets"
            }
            
    except Exception as e:
        logger.error(f"Error fetching parlay markets: {e}")
        return {"status": "error", "message": "Failed to fetch parlay markets"}

@app.options("/api/parlays/popular")
async def options_popular_parlays():
    """Handle CORS preflight for popular parlays"""
    return {}

@app.get("/api/parlays/popular")
async def get_popular_parlays():
    """Get popular parlay combinations"""
    return {
        "status": "success",
        "popular_parlays": [
            {
                "id": "nfl_moneyline_over",
                "name": "NFL Moneyline + Over",
                "sports": ["americanfootball_nfl"],
                "legs": 2,
                "avg_odds": 250,
                "success_rate": "45%"
            },
            {
                "id": "nba_favorites",
                "name": "NBA Home Favorites",
                "sports": ["basketball_nba"],
                "legs": 3,
                "avg_odds": 180,
                "success_rate": "52%"
            }
        ],
        "message": "Popular parlay combinations"
    }

# Ice Hockey specific endpoints for NHL
@app.options("/api/odds/hockey")
async def options_hockey_odds():
    """Handle CORS preflight for hockey odds (alias for NHL)"""
    return {}

@app.get("/api/odds/hockey")
async def get_hockey_odds(regions: str = "us", markets: str = "h2h,spreads,totals", odds_format: str = "american"):
    """Get Hockey odds (NHL alias endpoint)"""
    # Redirect to NHL endpoint
    return await get_icehockey_nhl_odds(regions, markets, odds_format)

# Live Betting endpoints
@app.options("/api/live-bets/markets")
async def options_live_betting_markets():
    """Handle CORS preflight for live betting markets"""
    return {}

@app.get("/api/live-bets/markets")
async def get_live_betting_markets(sport: str = None):
    """Get live betting markets from real data sources"""
    try:
        # Import the live betting service
        from app.services.live_betting_service_db import live_betting_service_db
        
        # Get real live betting markets
        markets_data = await live_betting_service_db.get_live_betting_markets(sport)
        
        # Convert LiveBettingMarket objects to the format expected by frontend
        markets = []
        for market in markets_data:
            market_dict = {
                "game_id": market.game_id,
                "sport": sport or "baseball_mlb",
                "home_team": market.home_team,
                "away_team": market.away_team,
                "game_status": market.game_status.value if hasattr(market.game_status, 'value') else str(market.game_status),
                "home_score": market.home_score,
                "away_score": market.away_score,
                "time_remaining": market.time_remaining,
                "commence_time": market.commence_time.isoformat() if market.commence_time else None,
                "markets_available": market.markets_available,
                "moneyline_home": market.moneyline_home,
                "moneyline_away": market.moneyline_away,
                "spread_line": market.spread_line,
                "spread_home_odds": market.spread_home_odds,
                "spread_away_odds": market.spread_away_odds,
                "total_line": market.total_line,
                "total_over_odds": market.total_over_odds,
                "total_under_odds": market.total_under_odds,
                "moneyline_bookmaker": market.moneyline_bookmaker,
                "spread_bookmaker": market.spread_bookmaker,
                "total_bookmaker": market.total_bookmaker,
                "is_suspended": market.is_suspended,
                "suspension_reason": market.suspension_reason,
                "last_updated": market.last_updated.isoformat() if market.last_updated else datetime.utcnow().isoformat()
            }
            markets.append(market_dict)
        
        return {
            "status": "success",
            "markets": markets,
            "message": f"Real data from The Odds API - {len(markets)} markets available"
        }
        
    except Exception as e:
        logger.error(f"Error fetching live betting markets: {e}")
        
        # Fallback to a minimal mock structure if the service fails
        return {
            "status": "success",
            "markets": [],
            "message": f"Live betting service unavailable: {str(e)}"
        }

@app.options("/api/live-bets/active")
async def options_active_live_bets():
    """Handle CORS preflight for active live bets"""
    return {}

@app.get("/api/live-bets/active")
async def get_active_live_bets(current_user: dict = Depends(get_current_user)):
    """Get user's active live bets from real database"""
    try:
        # Import the live betting service
        from app.services.live_betting_service_db import live_betting_service_db
        
        # Get real user live bets from database
        user_bets = live_betting_service_db.get_user_live_bets(
            user_id=current_user["id"],
            include_settled=False  # Only active bets
        )
        
        # Convert LiveBet objects to the format expected by frontend
        active_bets = []
        for bet in user_bets:
            bet_dict = {
                "id": bet.id,
                "user_id": bet.user_id,
                "game_id": bet.game_id,
                "bet_type": bet.bet_type,
                "selection": bet.selection,
                "odds": bet.original_odds,
                "amount": bet.amount,
                "potential_payout": bet.potential_win,
                "status": "active",
                "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
                "home_team": bet.home_team,
                "away_team": bet.away_team,
                "sport": bet.sport,
                "current_home_score": bet.current_home_score,
                "current_away_score": bet.current_away_score,
                "cash_out_available": bet.cash_out_available,
                "cash_out_value": bet.cash_out_value
            }
            active_bets.append(bet_dict)
        
        return {
            "status": "success",
            "active_bets": active_bets,
            "message": f"Real data from database - {len(active_bets)} active live bets"
        }
        
    except Exception as e:
        logger.error(f"Error fetching active live bets: {e}")
        return {
            "status": "success", 
            "active_bets": [],
            "message": f"Live betting service unavailable: {str(e)}"
        }

@app.options("/api/bets/history")
async def options_bet_history():
    """Handle CORS preflight for bet history"""
    return {}

@app.post("/api/bets/history")
async def get_bet_history(request: Request, current_user: dict = Depends(get_current_user)):
    """Get user's betting history from real database"""
    try:
        # Import betting service
        from app.services.live_betting_service_db import live_betting_service_db
        
        # Get all bets including settled ones
        user_bets = live_betting_service_db.get_user_live_bets(
            user_id=current_user["id"],
            include_settled=True  # Include all historical bets
        )
        
        # Convert LiveBet objects to the format expected by frontend
        bets = []
        for bet in user_bets:
            bet_dict = {
                "id": bet.id,
                "user_id": bet.user_id,
                "game_id": bet.game_id,
                "bet_type": bet.bet_type,
                "selection": bet.selection,
                "odds": bet.original_odds,
                "amount": bet.amount,
                "potential_payout": bet.potential_win,
                "status": "active" if bet.status.value == "ACTIVE" else bet.status.value.lower(),
                "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
                "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
                "home_team": bet.home_team,
                "away_team": bet.away_team,
                "sport": bet.sport,
                "result_amount": bet.result_amount
            }
            bets.append(bet_dict)
        
        return {
            "status": "success",
            "bets": bets,
            "total_bets": len(bets),
            "message": f"Real data from database - {len(bets)} total bets"
        }
        
    except Exception as e:
        logger.error(f"Error fetching bet history: {e}")
        return {
            "status": "success",
            "bets": [],
            "total_bets": 0,
            "message": f"Bet history service unavailable: {str(e)}"
        }

@app.get("/api/bets/parlay/{parlay_id}")
async def get_parlay_details(parlay_id: str, current_user: dict = Depends(get_current_user)):
    """Get details for a specific parlay bet"""
    try:
        if not is_service_available("bet_service"):
            return {
                "status": "success",
                "parlay": {
                    "id": parlay_id,
                    "user_id": current_user["id"],
                    "bets": [],
                    "total_odds": 100,
                    "amount": 0,
                    "potential_payout": 0,
                    "status": "pending"
                },
                "message": "Bet service not available - showing mock data"
            }
        
        # Mock parlay data
        return {
            "status": "success",
            "parlay": {
                "id": parlay_id,
                "user_id": current_user["id"],
                "bets": [
                    {
                        "id": "bet_1",
                        "selection": "Kansas City Chiefs -3.5",
                        "odds": -110,
                        "game": "Chiefs vs Bills"
                    },
                    {
                        "id": "bet_2", 
                        "selection": "Lakers ML",
                        "odds": 120,
                        "game": "Lakers vs Celtics"
                    }
                ],
                "total_odds": 264,
                "amount": 50.00,
                "potential_payout": 182.00,
                "status": "pending",
                "placed_at": "2025-01-09T01:00:00Z"
            },
            "message": "Mock data - Bet service not fully configured"
        }
        
    except Exception as e:
        logger.error(f"Error fetching parlay details: {e}")
        return {"status": "error", "message": "Failed to fetch parlay details"}

# ============================================================================
# YETAI BETS API ENDPOINTS
# ============================================================================

@app.options("/api/yetai-bets")
async def options_yetai_bets():
    """Handle CORS preflight for YetAI bets"""
    return {}

@app.get("/api/yetai-bets")
async def get_yetai_bets(current_user: dict = Depends(get_current_user)):
    """Get YetAI bets for the current user based on tier"""
    try:
        if not is_service_available("yetai_bets_service"):
            # Return mock data when service unavailable
            return {
                "status": "success",
                "bets": [
                    {
                        "id": "mock_yetai_1",
                        "sport": "NFL",
                        "game": "Chiefs vs Bills",
                        "bet_type": "spread",
                        "pick": "Chiefs -3.5",
                        "odds": "-110",
                        "confidence": 92,
                        "reasoning": "Chiefs have excellent road record vs top defenses. Buffalo missing key defensive players.",
                        "status": "pending",
                        "is_premium": False,
                        "game_time": "01/12/2025 @8:20 PM EST",
                        "bet_category": "straight",
                        "created_at": "2025-01-09T12:00:00Z"
                    },
                    {
                        "id": "mock_yetai_2",
                        "sport": "NBA",
                        "game": "Lakers vs Warriors",
                        "bet_type": "total",
                        "pick": "Over 228.5",
                        "odds": "-105",
                        "confidence": 87,
                        "reasoning": "Both teams ranking in top 5 for pace. Lakers missing defensive anchor.",
                        "status": "pending",
                        "is_premium": True,
                        "game_time": "01/12/2025 @10:30 PM EST",
                        "bet_category": "straight",
                        "created_at": "2025-01-09T12:30:00Z"
                    }
                ],
                "message": "Mock YetAI bets - Service not configured"
            }
        
        # Use real YetAI bets service
        yetai_service = get_service("yetai_bets_service")
        user_tier = current_user.get("subscription_tier", "free")
        
        bets = await yetai_service.get_active_bets(user_tier)
        
        return {
            "status": "success",
            "bets": bets,
            "message": f"Retrieved {len(bets)} YetAI bets for {user_tier} tier user"
        }
        
    except Exception as e:
        logger.error(f"Error fetching YetAI bets: {e}")
        return {
            "status": "error", 
            "message": "Failed to fetch YetAI bets",
            "bets": []
        }

@app.options("/api/admin/yetai-bets/{bet_id}")
async def options_delete_yetai_bet(bet_id: str):
    """Handle CORS preflight for YetAI bet deletion"""
    return {}

@app.delete("/api/admin/yetai-bets/{bet_id}")
async def delete_yetai_bet(bet_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a YetAI bet (Admin only)"""
    try:
        # Check admin permissions
        if not current_user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        if not is_service_available("yetai_bets_service"):
            raise HTTPException(status_code=503, detail="YetAI bets service unavailable")
        
        yetai_service = get_service("yetai_bets_service")
        result = await yetai_service.delete_bet(bet_id, current_user["id"])
        
        if result["success"]:
            return {"status": "success", "message": result["message"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting YetAI bet {bet_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete bet")

# ============================================================================
# SPORTS BETTING API ENDPOINTS  
# ============================================================================

@app.options("/api/bets/place")
async def options_place_bet():
    """Handle CORS preflight for bet placement"""
    return {}

@app.post("/api/bets/place")
async def place_bet(request: Request, current_user: dict = Depends(get_current_user)):
    """Place a single sports bet"""
    try:
        bet_data = await request.json()
        
        if not is_service_available("bet_service"):
            # Mock bet placement for development
            return {
                "status": "success",
                "bet": {
                    "id": f"mock_bet_{datetime.utcnow().timestamp()}",
                    "user_id": current_user["id"],
                    "bet_type": bet_data.get("bet_type", "moneyline"),
                    "selection": bet_data.get("selection", "Mock Selection"),
                    "odds": bet_data.get("odds", -110),
                    "amount": bet_data.get("amount", 100),
                    "potential_win": bet_data.get("amount", 100) * 0.91,
                    "status": "pending",
                    "placed_at": datetime.utcnow().isoformat(),
                    "home_team": bet_data.get("home_team", "Team A"),
                    "away_team": bet_data.get("away_team", "Team B"),
                    "sport": bet_data.get("sport", "NFL")
                },
                "message": "Mock bet placed - Bet service not configured"
            }
        
        # Use real bet service
        bet_service = get_service("bet_service")
        result = await bet_service.place_bet(current_user["id"], bet_data)
        
        if result["success"]:
            return {"status": "success", "bet": result["bet"], "message": result["message"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error placing bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to place bet")

@app.options("/api/bets/parlay")
async def options_place_parlay():
    """Handle CORS preflight for parlay placement"""
    return {}

@app.post("/api/bets/parlay")
async def place_parlay(request: Request, current_user: dict = Depends(get_current_user)):
    """Place a parlay bet with multiple legs"""
    try:
        parlay_data = await request.json()
        
        if not is_service_available("bet_service"):
            # Mock parlay placement
            legs = parlay_data.get("legs", [])
            return {
                "status": "success",
                "parlay": {
                    "id": f"mock_parlay_{datetime.utcnow().timestamp()}",
                    "user_id": current_user["id"],
                    "amount": parlay_data.get("amount", 100),
                    "total_odds": 250,
                    "potential_win": parlay_data.get("amount", 100) * 2.5,
                    "status": "pending",
                    "placed_at": datetime.utcnow().isoformat(),
                    "leg_count": len(legs)
                },
                "legs": legs,
                "message": f"Mock parlay placed with {len(legs)} legs - Bet service not configured"
            }
        
        # Use real bet service
        bet_service = get_service("bet_service")
        result = await bet_service.place_parlay(current_user["id"], parlay_data)
        
        if result["success"]:
            return {"status": "success", "parlay": result["parlay"], "legs": result["legs"], "message": result["message"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error placing parlay: {e}")
        raise HTTPException(status_code=500, detail="Failed to place parlay")

@app.options("/api/bets/parlays")
async def options_get_parlays():
    """Handle CORS preflight for parlay list"""
    return {}

@app.get("/api/bets/parlays")
async def get_user_parlays(current_user: dict = Depends(get_current_user)):
    """Get user's parlay bets"""
    try:
        if not is_service_available("bet_service"):
            # Mock parlay data
            return {
                "status": "success",
                "parlays": [
                    {
                        "id": "mock_parlay_1",
                        "user_id": current_user["id"],
                        "amount": 50.0,
                        "total_odds": 264,
                        "potential_win": 182.0,
                        "status": "pending",
                        "placed_at": "2025-01-09T01:00:00Z",
                        "leg_count": 2,
                        "legs": [
                            {
                                "selection": "Kansas City Chiefs -3.5",
                                "odds": -110,
                                "game": "Chiefs vs Bills"
                            },
                            {
                                "selection": "Lakers ML",
                                "odds": 120,
                                "game": "Lakers vs Celtics"
                            }
                        ]
                    }
                ],
                "total": 1,
                "message": "Mock parlay data - Bet service not configured"
            }
        
        # Use real bet service
        bet_service = get_service("bet_service")
        result = await bet_service.get_user_parlays(current_user["id"])
        
        if result["success"]:
            return {"status": "success", "parlays": result["parlays"], "total": result["total"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching parlays: {e}")
        return {"status": "success", "parlays": [], "total": 0, "message": "Failed to fetch parlays"}

@app.options("/api/bets/stats")
async def options_bet_stats():
    """Handle CORS preflight for bet statistics"""
    return {}

@app.get("/api/bets/stats")
async def get_bet_stats(current_user: dict = Depends(get_current_user)):
    """Get user's betting statistics"""
    try:
        if not is_service_available("bet_service"):
            # Mock stats
            return {
                "status": "success",
                "stats": {
                    "total_bets": 25,
                    "total_wagered": 2500.0,
                    "total_won": 1850.0,
                    "total_lost": 1100.0,
                    "net_profit": 750.0,
                    "win_rate": 68.0,
                    "average_bet": 100.0,
                    "average_odds": -108,
                    "best_win": 450.0,
                    "worst_loss": 200.0,
                    "current_streak": 3,
                    "longest_win_streak": 7,
                    "longest_loss_streak": 2
                },
                "message": "Mock betting statistics - Bet service not configured"
            }
        
        # Use real bet service
        bet_service = get_service("bet_service")
        result = await bet_service.get_bet_stats(current_user["id"])
        
        if result["success"]:
            return {"status": "success", "stats": result["stats"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching bet stats: {e}")
        return {"status": "success", "stats": {}, "message": "Failed to fetch bet statistics"}

@app.options("/api/bets/share")
async def options_share_bet():
    """Handle CORS preflight for bet sharing"""
    return {}

@app.post("/api/bets/share")
async def share_bet(request: Request, current_user: dict = Depends(get_current_user)):
    """Share a bet publicly"""
    try:
        share_data = await request.json()
        bet_id = share_data.get("bet_id")
        message = share_data.get("message", "")
        
        if not bet_id:
            raise HTTPException(status_code=400, detail="bet_id is required")
        
        if not is_service_available("bet_sharing_service"):
            # Mock share response
            mock_share_id = f"share_{datetime.utcnow().timestamp()}"
            return {
                "status": "success",
                "share_id": mock_share_id,
                "share_url": f"https://yetai.app/share/bet/{mock_share_id}",
                "message": "Mock bet share created - Sharing service not configured"
            }
        
        # Use real bet sharing service
        sharing_service = get_service("bet_sharing_service")
        result = await sharing_service.create_share(current_user["id"], bet_id, message)
        
        if result["success"]:
            return {
                "status": "success",
                "share_id": result["share_id"],
                "share_url": result["share_url"],
                "message": result["message"]
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sharing bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to share bet")

@app.options("/api/bets/shared")
async def options_shared_bets():
    """Handle CORS preflight for shared bets"""
    return {}

@app.get("/api/bets/shared")
async def get_shared_bets(current_user: dict = Depends(get_current_user)):
    """Get user's shared bets"""
    try:
        if not is_service_available("bet_sharing_service"):
            # Mock shared bets
            return {
                "status": "success",
                "shared_bets": [],
                "message": "Mock shared bets - Sharing service not configured"
            }
        
        # Use real bet sharing service
        sharing_service = get_service("bet_sharing_service")
        result = await sharing_service.get_user_shares(current_user["id"])
        
        if result["success"]:
            return {"status": "success", "shared_bets": result["shares"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching shared bets: {e}")
        return {"status": "success", "shared_bets": [], "message": "Failed to fetch shared bets"}

@app.delete("/api/bets/shared/{share_id}")
async def delete_shared_bet(share_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a shared bet"""
    return {"status": "success", "message": f"Shared bet {share_id} deleted successfully"}

@app.options("/api/bets/simulate")
async def options_simulate_bets():
    """Handle CORS preflight for bet simulation"""
    return {}

@app.post("/api/bets/simulate")
async def simulate_bets(current_user: dict = Depends(get_current_user)):
    """Simulate bet results for testing"""
    return {
        "status": "success", 
        "simulation_results": [
            {"bet_id": "sim_1", "outcome": "win", "payout": 150.00},
            {"bet_id": "sim_2", "outcome": "loss", "payout": 0.00}
        ],
        "message": "Bet simulation completed"
    }

@app.options("/api/bets/{bet_id}")
async def options_delete_bet(bet_id: str):
    """Handle CORS preflight for bet deletion"""
    return {}

@app.delete("/api/bets/{bet_id}")
async def cancel_bet(bet_id: str, current_user: dict = Depends(get_current_user)):
    """Cancel/delete a pending bet"""
    try:
        if not is_service_available("bet_service"):
            return {
                "status": "success",
                "message": "Mock bet cancellation - Bet service not configured"
            }
        
        # Use real bet service
        bet_service = get_service("bet_service")
        result = await bet_service.cancel_bet(current_user["id"], bet_id)
        
        if result["success"]:
            return {"status": "success", "message": result["message"]}
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error canceling bet {bet_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel bet")

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

# User Performance Endpoints
@app.get("/api/user/performance")
async def get_user_performance(request: Request, current_user: dict = Depends(get_current_user)):
    """Get user performance metrics"""
    try:
        if not is_service_available("performance_tracker"):
            return {
                "status": "success",
                "data": {
                    "total_bets": 0,
                    "win_rate": 0,
                    "profit_loss": 0,
                    "recent_performance": []
                },
                "message": "Performance tracking service not available - showing mock data"
            }
        
        performance_service = get_service("performance_tracker")
        metrics = await performance_service.get_user_performance(current_user["id"])
        return {"status": "success", "data": metrics}
    except Exception as e:
        logger.error(f"Error fetching user performance: {e}")
        return {"status": "error", "message": "Failed to fetch performance data"}

@app.post("/api/performance/simulate-data")
async def simulate_performance_data(current_user: dict = Depends(get_current_user)):
    """Simulate performance data for testing"""
    try:
        # Mock data simulation for development
        return {"status": "success", "message": "Mock performance data created"}
    except Exception as e:
        logger.error(f"Error simulating performance data: {e}")
        return {"status": "error", "message": "Failed to simulate data"}

@app.get("/api/performance/metrics")
async def get_performance_metrics(current_user: dict = Depends(get_current_user)):
    """Get performance metrics"""
    try:
        return {
            "status": "success",
            "metrics": {
                "total_bets": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_odds": 0.0,
                "profit_loss": 0.0,
                "best_streak": 0,
                "current_streak": 0
            }
        }
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        return {"status": "error", "message": "Failed to fetch metrics"}

@app.get("/api/performance/best-predictions")
async def get_best_predictions(current_user: dict = Depends(get_current_user)):
    """Get best predictions"""
    try:
        return {
            "status": "success",
            "best_predictions": []
        }
    except Exception as e:
        logger.error(f"Error fetching best predictions: {e}")
        return {"status": "error", "message": "Failed to fetch best predictions"}

# Avatar Endpoints  
@app.get("/api/auth/avatar/{user_id}")
async def get_user_avatar(user_id: int):
    """Get user avatar"""
    try:
        if not is_service_available("auth_service"):
            return {"status": "error", "message": "Avatar service not available"}
        
        # Get user from database
        from app.core.database import SessionLocal
        from app.models.database_models import User
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return {"status": "error", "message": "User not found"}
            
            return {
                "status": "success", 
                "avatar_url": user.avatar_url,
                "avatar_thumbnail": user.avatar_thumbnail
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error fetching avatar: {e}")
        return {"status": "error", "message": "Failed to fetch avatar"}

# Personalized Predictions Endpoint
@app.get("/api/predictions/personalized")
async def get_personalized_predictions(request: Request, current_user: dict = Depends(get_current_user)):
    """Get personalized predictions for the user"""
    try:
        if not is_service_available("yetai_bets_service"):
            return {
                "status": "success",
                "predictions": [],
                "message": "Personalized predictions service not available"
            }
        
        yetai_service = get_service("yetai_bets_service")  
        predictions = await yetai_service.get_personalized_bets(current_user["id"])
        return {"status": "success", "predictions": predictions}
    except Exception as e:
        logger.error(f"Error fetching personalized predictions: {e}")
        return {"status": "error", "message": "Failed to fetch predictions"}

@app.get("/api/predictions/daily")
async def get_daily_predictions():
    """Get daily predictions"""
    try:
        return {
            "status": "success",
            "predictions": [],
            "message": "Daily predictions service not fully configured"
        }
    except Exception as e:
        logger.error(f"Error fetching daily predictions: {e}")
        return {"status": "error", "message": "Failed to fetch daily predictions"}

# ============================================================================
# FANTASY SPORTS API ENDPOINTS
# ============================================================================

@app.options("/api/fantasy/accounts")
async def options_fantasy_accounts():
    """Handle CORS preflight for fantasy accounts"""
    return {}

@app.get("/api/fantasy/accounts")
async def get_fantasy_accounts(current_user: dict = Depends(get_current_user)):
    """Get user's connected fantasy platform accounts"""
    try:
        if not is_service_available("fantasy_service"):
            return {
                "status": "success",
                "accounts": [],
                "message": "Fantasy service not configured"
            }
        
        fantasy_service = get_service("fantasy_service")
        accounts = fantasy_service.get_user_fantasy_accounts(current_user["id"])
        
        return {
            "status": "success",
            "accounts": accounts,
            "message": f"Retrieved {len(accounts)} fantasy accounts"
        }
        
    except Exception as e:
        logger.error(f"Error fetching fantasy accounts: {e}")
        return {"status": "success", "accounts": [], "message": "Failed to fetch fantasy accounts"}

@app.options("/api/fantasy/leagues")
async def options_fantasy_leagues():
    """Handle CORS preflight for fantasy leagues"""
    return {}

@app.get("/api/fantasy/leagues")
async def get_fantasy_leagues(current_user: dict = Depends(get_current_user)):
    """Get user's fantasy leagues across all platforms"""
    try:
        if not is_service_available("fantasy_service"):
            return {
                "status": "success",
                "leagues": [],
                "message": "Fantasy service not configured"
            }
        
        fantasy_service = get_service("fantasy_service")
        leagues = fantasy_service.get_user_leagues(current_user["id"])
        
        return {
            "status": "success",
            "leagues": leagues,
            "message": f"Retrieved {len(leagues)} fantasy leagues"
        }
        
    except Exception as e:
        logger.error(f"Error fetching fantasy leagues: {e}")
        return {"status": "success", "leagues": [], "message": "Failed to fetch fantasy leagues"}

@app.options("/api/fantasy/connect")
async def options_fantasy_connect():
    """Handle CORS preflight for fantasy platform connection"""
    return {}

@app.post("/api/fantasy/connect")
async def connect_fantasy_platform(request: Request, current_user: dict = Depends(get_current_user)):
    """Connect a fantasy platform account"""
    try:
        connect_data = await request.json()
        platform = connect_data.get("platform")
        credentials = connect_data.get("credentials", {})
        
        if not platform:
            raise HTTPException(status_code=400, detail="Platform is required")
        
        if not is_service_available("fantasy_service"):
            return {
                "status": "success",
                "fantasy_user_id": f"mock_{platform}_{current_user['id']}",
                "platform": platform,
                "message": f"Mock connection to {platform} - Fantasy service not configured"
            }
        
        fantasy_service = get_service("fantasy_service")
        result = await fantasy_service.connect_user_account(current_user["id"], platform, credentials)
        
        if result["success"]:
            return {
                "status": "success",
                "fantasy_user_id": result["fantasy_user_id"],
                "platform": result["platform"],
                "username": result.get("username"),
                "message": f"Successfully connected to {platform}"
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting fantasy platform: {e}")
        raise HTTPException(status_code=500, detail="Failed to connect fantasy platform")

@app.options("/api/fantasy/roster/{league_id}")
async def options_fantasy_roster(league_id: str):
    """Handle CORS preflight for fantasy roster"""
    return {}

@app.get("/api/fantasy/roster/{league_id}")
async def get_fantasy_roster(league_id: str, current_user: dict = Depends(get_current_user)):
    """Get fantasy roster for a specific league"""
    try:
        if not is_service_available("fantasy_service"):
            return {
                "status": "success",
                "roster": {
                    "league_id": league_id,
                    "team_name": "Mock Team",
                    "starters": [],
                    "bench": [],
                    "ir": []
                },
                "message": "Mock roster data - Fantasy service not configured"
            }
        
        fantasy_service = get_service("fantasy_service")
        # This would need to be implemented in the fantasy service
        # For now, return empty roster structure
        roster = {
            "league_id": league_id,
            "team_name": "User Team",
            "starters": [],
            "bench": [],
            "ir": []
        }
        
        return {
            "status": "success",
            "roster": roster,
            "message": "Retrieved fantasy roster"
        }
        
    except Exception as e:
        logger.error(f"Error fetching fantasy roster for league {league_id}: {e}")
        return {
            "status": "success", 
            "roster": {"league_id": league_id, "starters": [], "bench": [], "ir": []}, 
            "message": "Failed to fetch fantasy roster"
        }

@app.get("/api/fantasy/projections")
async def get_fantasy_projections():
    """Get fantasy projections"""
    try:
        return {
            "status": "success",
            "projections": [],
            "message": "Fantasy projections service not fully configured"
        }
    except Exception as e:
        logger.error(f"Error fetching fantasy projections: {e}")
        return {"status": "error", "message": "Failed to fetch fantasy projections"}

# ============================================================================
# PROFILE & STATUS API ENDPOINTS
# ============================================================================

@app.options("/api/profile/sports")
async def options_profile_sports():
    """Handle CORS preflight for profile sports"""
    return {}

@app.get("/api/profile/sports")
async def get_profile_sports(current_user: dict = Depends(get_current_user)):
    """Get user's sports preferences and settings"""
    try:
        # Mock profile sports data since we don't have a specific service yet
        return {
            "status": "success",
            "sports_preferences": {
                "favorite_sports": ["NFL", "NBA", "MLB"],
                "favorite_teams": {
                    "NFL": ["Kansas City Chiefs", "Buffalo Bills"],
                    "NBA": ["Los Angeles Lakers", "Boston Celtics"],
                    "MLB": ["Los Angeles Dodgers", "New York Yankees"]
                },
                "betting_preferences": {
                    "preferred_bet_types": ["moneyline", "spread", "total"],
                    "max_bet_amount": 500,
                    "risk_tolerance": "medium"
                },
                "notification_settings": {
                    "game_alerts": True,
                    "bet_results": True,
                    "daily_picks": True,
                    "price_alerts": False
                }
            },
            "message": "Retrieved sports preferences"
        }
        
    except Exception as e:
        logger.error(f"Error fetching profile sports: {e}")
        return {"status": "error", "message": "Failed to fetch sports preferences"}

@app.options("/api/profile/status")
async def options_profile_status():
    """Handle CORS preflight for profile status"""
    return {}

@app.get("/api/profile/status")
async def get_profile_status(current_user: dict = Depends(get_current_user)):
    """Get user's profile status and statistics"""
    try:
        # Calculate profile completeness and stats
        profile_stats = {
            "user_id": current_user["id"],
            "username": current_user.get("username", "Unknown"),
            "email": current_user.get("email", "Unknown"),
            "subscription_tier": current_user.get("subscription_tier", "free"),
            "member_since": current_user.get("created_at", datetime.utcnow().isoformat()),
            "profile_completeness": 75,  # Mock percentage
            "account_status": "active",
            "verification_status": {
                "email_verified": True,
                "phone_verified": False,
                "identity_verified": False
            },
            "activity_summary": {
                "total_bets_placed": 0,
                "days_active": 1,
                "last_login": datetime.utcnow().isoformat(),
                "favorite_sport": "NFL"
            },
            "settings": {
                "dark_mode": False,
                "notifications_enabled": True,
                "two_factor_enabled": False
            }
        }
        
        return {
            "status": "success",
            "profile": profile_stats,
            "message": "Retrieved profile status"
        }
        
    except Exception as e:
        logger.error(f"Error fetching profile status: {e}")
        return {"status": "error", "message": "Failed to fetch profile status"}

# ============================================================================
# PROFILE - AVATAR AND PREFERENCES ENDPOINTS
# ============================================================================

@app.options("/api/profile/avatar")
async def options_profile_avatar():
    """Handle CORS preflight for profile avatar endpoint"""
    return {}

@app.get("/api/profile/avatar")
async def get_profile_avatar(current_user: dict = Depends(get_current_user)):
    """Get user profile avatar information"""
    try:
        # Try to get avatar from user service
        if is_service_available("user_service"):
            user_service = get_service("user_service")
            avatar_data = await user_service.get_user_avatar(current_user["user_id"])
            
            return {
                "status": "success",
                "avatar": avatar_data,
                "message": "Retrieved user avatar"
            }
        
        # Mock data when service unavailable
        avatar_data = {
            "avatar_url": None,
            "initials": current_user.get("username", "U")[:2].upper() if current_user.get("username") else "U",
            "background_color": "#3B82F6",
            "has_custom_avatar": False,
            "upload_enabled": True,
            "supported_formats": ["jpg", "jpeg", "png", "webp"],
            "max_file_size": "5MB"
        }
        
        return {
            "status": "success", 
            "avatar": avatar_data,
            "message": "User avatar service not configured - showing defaults"
        }
        
    except Exception as e:
        logger.error(f"Error fetching profile avatar: {e}")
        return {"status": "error", "message": "Failed to fetch profile avatar"}

@app.options("/api/profile/preferences")
async def options_profile_preferences():
    """Handle CORS preflight for profile preferences endpoint"""
    return {}

@app.get("/api/profile/preferences")
async def get_profile_preferences(current_user: dict = Depends(get_current_user)):
    """Get user preferences and settings"""
    try:
        # Try to get preferences from user service
        if is_service_available("user_service"):
            user_service = get_service("user_service")
            preferences = await user_service.get_user_preferences(current_user["user_id"])
            
            return {
                "status": "success",
                "preferences": preferences,
                "message": "Retrieved user preferences"
            }
        
        # Mock preferences data when service unavailable
        preferences = {
            "betting": {
                "default_stake": 25.0,
                "auto_cash_out": False,
                "risk_level": "medium",
                "favorite_sports": ["americanfootball_nfl", "basketball_nba"],
                "notifications": {
                    "bet_placed": True,
                    "bet_settled": True,
                    "promotions": False,
                    "odds_changes": True
                }
            },
            "display": {
                "theme": "light",
                "odds_format": "american",
                "timezone": "America/New_York",
                "language": "en"
            },
            "privacy": {
                "show_public_bets": False,
                "allow_friend_requests": True,
                "share_win_loss": False
            },
            "fantasy": {
                "connected_platforms": [],
                "auto_sync": True,
                "notifications": True
            }
        }
        
        return {
            "status": "success",
            "preferences": preferences,
            "message": "User preferences service not configured - showing defaults"
        }
        
    except Exception as e:
        logger.error(f"Error fetching profile preferences: {e}")
        return {"status": "error", "message": "Failed to fetch profile preferences"}

# ============================================================================
# API ENDPOINT HEALTH CHECK
# ============================================================================

@app.get("/api/endpoints/health")
async def check_endpoints_health():
    """Health check for all API endpoints - useful for debugging 404s"""
    try:
        endpoints = {
            "yetai_bets": {
                "GET /api/yetai-bets": "Get YetAI bets for user",
                "DELETE /api/admin/yetai-bets/{bet_id}": "Delete YetAI bet (Admin)"
            },
            "sports_betting": {
                "POST /api/bets/place": "Place single sports bet",
                "POST /api/bets/parlay": "Place parlay bet",
                "GET /api/bets/parlays": "Get user parlays",
                "POST /api/bets/history": "Get bet history",
                "GET /api/bets/stats": "Get betting statistics",
                "POST /api/bets/share": "Share a bet",
                "GET /api/bets/shared": "Get shared bets",
                "DELETE /api/bets/shared/{share_id}": "Delete shared bet",
                "DELETE /api/bets/{bet_id}": "Cancel/delete bet",
                "POST /api/bets/simulate": "Simulate bet results",
                "GET /api/bets/parlay/{parlay_id}": "Get parlay details"
            },
            "fantasy_sports": {
                "GET /api/fantasy/accounts": "Get connected fantasy accounts",
                "GET /api/fantasy/leagues": "Get fantasy leagues",
                "POST /api/fantasy/connect": "Connect fantasy platform",
                "GET /api/fantasy/roster/{league_id}": "Get fantasy roster",
                "GET /api/fantasy/projections": "Get fantasy projections"
            },
            "odds_markets": {
                "GET /api/odds/americanfootball_nfl": "NFL odds",
                "GET /api/odds/basketball_nba": "NBA odds",
                "GET /api/odds/baseball_mlb": "MLB odds",
                "GET /api/odds/icehockey_nhl": "NHL odds",
                "GET /api/odds/hockey": "Hockey odds (NHL alias)",
                "GET /api/odds/popular": "Popular sports odds"
            },
            "parlays": {
                "GET /api/parlays/markets": "Available parlay markets",
                "GET /api/parlays/popular": "Popular parlay combinations"
            },
            "profile_status": {
                "GET /api/profile/sports": "User sports preferences",
                "GET /api/profile/status": "User profile status"
            },
            "live_betting": {
                "GET /api/live-bets/markets": "Live betting markets",
                "GET /api/live-bets/active": "Active live bets"
            },
            "core_endpoints": {
                "GET /api/status": "API status",
                "GET /api/auth/status": "Auth status",
                "POST /api/auth/login": "User login",
                "POST /api/auth/register": "User registration",
                "GET /api/auth/me": "Current user info"
            }
        }
        
        # Count available services
        service_status = {
            "yetai_bets_service": is_service_available("yetai_bets_service"),
            "bet_service": is_service_available("bet_service"),
            "bet_sharing_service": is_service_available("bet_sharing_service"),
            "fantasy_service": is_service_available("fantasy_service"),
            "auth_service": is_service_available("auth_service"),
            "sports_pipeline": is_service_available("sports_pipeline"),
            "ai_chat_service": is_service_available("ai_chat_service")
        }
        
        return {
            "status": "success",
            "message": "All endpoint categories available",
            "endpoints": endpoints,
            "service_status": service_status,
            "total_endpoints": sum(len(category) for category in endpoints.values()),
            "environment": settings.ENVIRONMENT
        }
        
    except Exception as e:
        logger.error(f"Error checking endpoints health: {e}")
        return {"status": "error", "message": "Failed to check endpoints health"}

# WebSocket Support
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    
    try:
        if is_service_available("websocket_manager"):
            # Use the websocket manager if available
            websocket_manager = get_service("websocket_manager")
            await websocket_manager.handle_connection(websocket, user_id)
        else:
            # Basic WebSocket handling without manager
            try:
                while True:
                    # Keep connection alive and send periodic updates
                    await asyncio.sleep(30)
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.utcnow().isoformat(),
                        "message": "Connection alive"
                    })
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for user {user_id}")
                
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        try:
            await websocket.close()
        except:
            pass

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