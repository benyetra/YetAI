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