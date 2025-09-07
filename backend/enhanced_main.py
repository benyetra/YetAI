"""
Enhanced FastAPI application for YetAI Sports Betting MVP
Gradually adding features from the original app/main.py
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

# Database imports - with error handling
try:
    from app.core.database import get_db, init_db, check_db_connection
    from app.core.config import settings
    DATABASE_AVAILABLE = True
    logger.info("Database modules loaded successfully")
except Exception as e:
    logger.warning(f"Database modules not available: {e}")
    DATABASE_AVAILABLE = False

# Service imports - with error handling
try:
    from app.services.data_pipeline import sports_pipeline
    SPORTS_PIPELINE_AVAILABLE = True
    logger.info("Sports pipeline loaded successfully")
except Exception as e:
    logger.warning(f"Sports pipeline not available: {e}")
    SPORTS_PIPELINE_AVAILABLE = False

try:
    from app.services.ai_chat_service import ai_chat_service
    AI_CHAT_SERVICE_AVAILABLE = True
    logger.info("AI chat service loaded successfully")
except Exception as e:
    logger.warning(f"AI chat service not available: {e}")
    AI_CHAT_SERVICE_AVAILABLE = False

# Chat Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None

# Create FastAPI app
app = FastAPI(
    title="YetAI Sports Betting MVP",
    description="AI-Powered Sports Betting Platform - Enhanced Version",
    version="1.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info("Starting YetAI Sports Betting MVP Enhanced")
    
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
        "message": "YetAI Sports Betting MVP API - Enhanced",
        "version": "1.1.0",
        "status": "running",
        "database_available": DATABASE_AVAILABLE,
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
        "environment": os.getenv("ENVIRONMENT", "development")
    }

@app.get("/api/status")
async def api_status():
    """API status endpoint for frontend"""
    return {
        "api_status": "online",
        "database_status": "connected" if DATABASE_AVAILABLE and check_db_connection() else "unavailable",
        "features": [
            "health_check",
            "database_integration",
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
            "message": "Sports pipeline not available",
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
        raise HTTPException(status_code=500, detail=f"Error fetching games: {str(e)}")

@app.get("/api/odds/nfl")
async def get_nfl_odds():
    """Get current NFL betting odds"""
    if not SPORTS_PIPELINE_AVAILABLE:
        return {
            "status": "error",
            "message": "Sports pipeline not available",
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
        raise HTTPException(status_code=500, detail=f"Error fetching odds: {str(e)}")

# AI Chat API endpoint
@app.post("/api/chat/message")
async def send_chat_message(request: ChatRequest):
    """Send a message to the AI chat assistant"""
    if not AI_CHAT_SERVICE_AVAILABLE:
        return {
            "status": "error",
            "message": "Chat service not available",
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
        raise HTTPException(status_code=500, detail=f"Error processing chat message: {str(e)}")

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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)