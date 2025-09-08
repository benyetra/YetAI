"""
Production-ready FastAPI application for YetAI Sports Betting MVP
Handles missing services gracefully for Railway deployment
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
import logging
import asyncio
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chat Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None

# Service availability flags
DATABASE_AVAILABLE = False
SPORTS_PIPELINE_AVAILABLE = False
AI_CHAT_SERVICE_AVAILABLE = False
AUTH_SERVICE_AVAILABLE = False

# Database imports - with error handling
try:
    from app.core.database import get_db, init_db, check_db_connection
    from app.core.config import settings
    DATABASE_AVAILABLE = True
    logger.info("Database modules loaded successfully")
except Exception as e:
    logger.warning(f"Database modules not available: {e}")

# Sports pipeline imports - with error handling
try:
    from app.services.data_pipeline import sports_pipeline
    SPORTS_PIPELINE_AVAILABLE = True
    logger.info("Sports pipeline loaded successfully")
except Exception as e:
    logger.warning(f"Sports pipeline not available: {e}")

# AI chat service imports - with error handling  
try:
    from app.services.ai_chat_service import ai_chat_service
    AI_CHAT_SERVICE_AVAILABLE = True
    logger.info("AI chat service loaded successfully")
except Exception as e:
    logger.warning(f"AI chat service not available: {e}")

# Auth service imports - with error handling
try:
    from app.services.auth_service_db import auth_service_db as auth_service
    AUTH_SERVICE_AVAILABLE = True
    logger.info("Auth service loaded successfully")
except Exception as e:
    logger.warning(f"Auth service not available: {e}")

# Create FastAPI app
app = FastAPI(
    title="YetAI Sports Betting MVP",
    description="AI-Powered Sports Betting Platform - Production Version",
    version="1.2.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://yetai.app",
        "https://yetai.vercel.app", 
        "https://*.vercel.app",
        "http://localhost:3000",  # For local development
        "http://localhost:8080"   # For local development
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info("Starting YetAI Sports Betting MVP Production")
    
    if DATABASE_AVAILABLE:
        try:
            if check_db_connection():
                logger.info("Database connected successfully")
                init_db()
                logger.info("Database tables initialized")
            else:
                logger.warning("Database connection failed")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
    else:
        logger.warning("Running without database connection")

@app.get("/")
async def root():
    return {
        "message": "YetAI Sports Betting MVP API - Production",
        "version": "1.2.0",
        "status": "running",
        "database_available": DATABASE_AVAILABLE,
        "services": {
            "database": DATABASE_AVAILABLE,
            "sports_pipeline": SPORTS_PIPELINE_AVAILABLE,
            "ai_chat": AI_CHAT_SERVICE_AVAILABLE,
            "auth": AUTH_SERVICE_AVAILABLE
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    db_status = "not_available"
    if DATABASE_AVAILABLE:
        try:
            db_status = "connected" if check_db_connection() else "disconnected"
        except Exception:
            db_status = "error"
    
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "services": {
            "database": DATABASE_AVAILABLE,
            "sports_pipeline": SPORTS_PIPELINE_AVAILABLE,
            "ai_chat": AI_CHAT_SERVICE_AVAILABLE
        }
    }

@app.get("/api/status")
async def api_status():
    """API status endpoint for frontend"""
    return {
        "api_status": "online",
        "database_status": "connected" if DATABASE_AVAILABLE and check_db_connection() else "unavailable",
        "features": [
            "health_check",
            "database_integration" if DATABASE_AVAILABLE else "database_unavailable",
            "sports_data" if SPORTS_PIPELINE_AVAILABLE else "sports_data_unavailable",
            "ai_chat" if AI_CHAT_SERVICE_AVAILABLE else "ai_chat_unavailable",
            "cors_enabled",
            "production_ready"
        ],
        "timestamp": datetime.now().isoformat()
    }

@app.get("/test-db")
async def test_database():
    """Test database connection"""
    if not DATABASE_AVAILABLE:
        return {
            "database": "not_configured",
            "status": "warning",
            "message": "Database modules not available"
        }
    
    try:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return {
                "database": "No DATABASE_URL configured",
                "status": "warning"
            }
        
        # Simple connection test
        import psycopg2
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return {
            "database": "connected",
            "status": "success",
            "result": result[0] if result else None,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return {
            "database": "connection failed",
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# NFL Games and Odds API endpoints
@app.get("/api/games/nfl")
async def get_nfl_games():
    """Get current NFL games"""
    if not SPORTS_PIPELINE_AVAILABLE:
        return {
            "status": "error",
            "message": "Sports pipeline not available - service starting up",
            "games": [],
            "count": 0
        }
    
    try:
        games = await sports_pipeline.get_nfl_games_today()
        return {
            "status": "success",
            "count": len(games),
            "games": games
        }
    except Exception as e:
        logger.error(f"Error fetching NFL games: {e}")
        return {
            "status": "error", 
            "message": f"Error fetching games: {str(e)}",
            "games": [],
            "count": 0
        }

@app.get("/api/odds/nfl")
async def get_nfl_odds():
    """Get current NFL betting odds"""
    if not SPORTS_PIPELINE_AVAILABLE:
        return {
            "status": "error",
            "message": "Sports pipeline not available - service starting up",
            "odds": [],
            "count": 0
        }
    
    try:
        odds = await sports_pipeline.get_nfl_odds()
        return {
            "status": "success",
            "count": len(odds),
            "odds": odds
        }
    except Exception as e:
        logger.error(f"Error fetching NFL odds: {e}")
        return {
            "status": "error",
            "message": f"Error fetching odds: {str(e)}",
            "odds": [],
            "count": 0
        }

# AI Chat API endpoint
@app.post("/api/chat/message")
async def send_chat_message(request: ChatRequest):
    """Send a message to the AI chat assistant"""
    if not AI_CHAT_SERVICE_AVAILABLE:
        return {
            "status": "error",
            "message": "AI chat service is currently unavailable. Please try again later.",
            "type": "error"
        }
    
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
        logger.error(f"Error processing chat message: {e}")
        return {
            "status": "error",
            "message": "Unable to process chat request at this time",
            "type": "error"
        }

@app.get("/api/chat/suggestions")
async def get_chat_suggestions():
    """Get quick suggestion prompts for the chat"""
    return {
        "status": "success",
        "suggestions": [
            "What are today's best NFL bets?",
            "Show me the latest odds for Sunday games", 
            "What's your prediction for the Chiefs game?",
            "Give me fantasy football advice for this week",
            "What should I know about tonight's matchup?"
        ]
    }

# Odds API endpoints
@app.get("/api/odds/popular")
async def get_popular_sports_odds():
    """Get odds for popular sports (NFL, NBA, MLB, NHL)"""
    # Return mock data for production since odds API is not configured
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
        "message": "Mock data - Odds API integration not fully configured in production"
    }

# Authentication API endpoints
@app.get("/api/auth/status")
async def auth_status():
    """Check authentication status"""
    return {
        "authenticated": False,
        "auth_available": AUTH_SERVICE_AVAILABLE,
        "message": "Authentication service ready" if AUTH_SERVICE_AVAILABLE else "Authentication service unavailable"
    }

@app.post("/api/auth/register")
async def register(user_data: dict):
    """Register a new user"""
    if not AUTH_SERVICE_AVAILABLE:
        raise HTTPException(
            status_code=503, 
            detail="Authentication service is currently unavailable"
        )
    
    try:
        result = await auth_service.create_user(
            email=user_data.get("email"),
            password=user_data.get("password"),
            username=user_data.get("email"),  # Use email as username
            first_name=user_data.get("full_name", "").split(" ")[0] if user_data.get("full_name") else "",
            last_name=" ".join(user_data.get("full_name", "").split(" ")[1:]) if user_data.get("full_name") and len(user_data.get("full_name", "").split(" ")) > 1 else ""
        )
        return {
            "status": "success",
            "message": "User registered successfully",
            "user_id": result.get("user_id")
        }
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
async def login(credentials: dict):
    """Login user"""
    if not AUTH_SERVICE_AVAILABLE:
        raise HTTPException(
            status_code=503, 
            detail="Authentication service is currently unavailable"
        )
    
    try:
        result = await auth_service.authenticate_user(
            email_or_username=credentials.get("email"),
            password=credentials.get("password")
        )
        return {
            "status": "success",
            "message": "Login successful",
            "token": result.get("token"),
            "user": result.get("user")
        }
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
    if not AUTH_SERVICE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Authentication service is currently unavailable"
        )
    
    return {
        "status": "success",
        "message": "Authentication endpoint available but token validation not implemented in production version",
        "user": None
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting production server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)