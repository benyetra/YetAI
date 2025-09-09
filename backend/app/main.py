"""
Environment-aware FastAPI application for YetAI Sports Betting MVP
Consolidates development and production functionality into a single file
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr
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

# Share Models
class ShareBetRequest(BaseModel):
    bet_id: str
    message: Optional[str] = None

# JWT Helper Functions
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Extract user from JWT token - simplified for now"""
    try:
        # In a real implementation, you'd decode and validate the JWT token here
        # For now, return a mock user or handle the token validation
        token = credentials.credentials
        
        # Basic validation (in production, decode JWT properly)
        invalid_token_value = "invalid"  # nosec B105 - this is a test token value, not a real password
        if not token or token == invalid_token_value:
            raise HTTPException(status_code=401, detail="Invalid token")
            
        # Mock user for development
        return {
            "user_id": "mock_user_123",
            "email": "user@example.com",
            "subscription_tier": "pro"  # or "free"
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed")

# Environment-aware CORS configuration
def get_cors_origins():
    """Get CORS origins based on environment using centralized configuration"""
    return settings.get_frontend_urls()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
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
    
    yield
    
    # Shutdown
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

# Create FastAPI app
app = FastAPI(
    title="YetAI Sports Betting MVP",
    description=f"AI-Powered Sports Betting Platform - {settings.ENVIRONMENT.title()} Environment",
    version="1.2.0",
    debug=settings.DEBUG,
    lifespan=lifespan
)

# Add CORS middleware with environment-aware origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Health and status endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway/deployment monitoring"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": service_loader.get_status()
    }

# User endpoints that frontend expects
@app.options("/api/user/performance")
async def options_user_performance():
    """Handle CORS preflight for user performance endpoint"""
    return {}

@app.get("/api/user/performance")
async def get_user_performance(current_user: dict = Depends(get_current_user)):
    """Get user performance metrics"""
    if is_service_available("performance_tracker"):
        try:
            performance_service = get_service("performance_tracker")
            metrics = await performance_service.get_user_metrics(current_user["user_id"])
            return {"status": "success", "metrics": metrics}
        except Exception as e:
            logger.error(f"Error fetching user performance: {e}")
    
    # Mock performance data
    return {
        "status": "success",
        "metrics": {
            "total_predictions": 25,
            "accuracy_rate": 0.68,
            "win_streak": 4,
            "total_earnings": 450.50,
            "roi": 0.125,
            "favorite_sport": "NFL",
            "predictions_this_week": 3,
            "weekly_accuracy": 0.75
        },
        "message": "Mock performance data - performance tracker unavailable"
    }

# Simple endpoints for bets and odds that frontend might expect
@app.options("/api/bets")
async def options_simple_bets():
    """Handle CORS preflight for simple bets endpoint"""
    return {}

@app.get("/api/bets")
async def get_simple_bets(current_user: dict = Depends(get_current_user)):
    """Get user's bets - simplified endpoint"""
    # Redirect to the proper bet history endpoint
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            bets = await bet_service.get_user_bets(current_user["user_id"])
            return {"status": "success", "bets": bets}
        except Exception as e:
            logger.error(f"Error fetching user bets: {e}")
    
    # Mock bet data
    return {
        "status": "success", 
        "bets": [
            {
                "id": "bet_1",
                "type": "moneyline", 
                "selection": "Kansas City Chiefs",
                "odds": -150,
                "amount": 100.0,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ],
        "message": "Mock bet data - bet service unavailable"
    }

@app.options("/api/odds")
async def options_simple_odds():
    """Handle CORS preflight for simple odds endpoint"""
    return {}

@app.get("/api/odds")  
async def get_simple_odds():
    """Get current odds - simplified endpoint"""
    # Redirect to popular odds endpoint
    return await get_popular_sports_odds()

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
        "timestamp": datetime.now(timezone.utc).isoformat()
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
async def get_current_user_info():
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

# YetAI Bets endpoints
@app.options("/api/yetai-bets")
async def options_yetai_bets():
    """Handle CORS preflight for YetAI bets endpoint"""
    return {}

@app.get("/api/yetai-bets")
async def get_yetai_bets(current_user: dict = Depends(get_current_user)):
    """Get YetAI bets for user based on subscription tier"""
    if is_service_available("yetai_bets_service"):
        try:
            yetai_service = get_service("yetai_bets_service")
            
            # Get user's subscription tier from the authenticated user
            user_tier = current_user.get("subscription_tier", "free")
            
            # Fetch bets based on user tier
            bets = await yetai_service.get_bets_for_tier(user_tier)
            
            return {
                "status": "success",
                "bets": bets,
                "user_tier": user_tier,
                "message": f"YetAI bets for {user_tier} tier user"
            }
        except Exception as e:
            logger.error(f"Error fetching YetAI bets: {e}")
            # Fall through to mock data
    
    # Return mock data when service unavailable
    user_tier = current_user.get("subscription_tier", "free")
    mock_bets = [
        {
            "id": "mock_yetai_1",
            "title": "Chiefs ML Lock",
            "description": "AI algorithm predicts 78% confidence on Chiefs moneyline",
            "bet_type": "moneyline",
            "selection": "Kansas City Chiefs",
            "odds": -150,
            "confidence": 0.78,
            "tier_requirement": "free" if user_tier == "free" else "pro",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    
    # Pro users get more bets
    if user_tier == "pro":
        mock_bets.append({
            "id": "mock_yetai_2", 
            "title": "Lakers Spread Value",
            "description": "Advanced analytics show Lakers covering the spread at 85% confidence",
            "bet_type": "spread",
            "selection": "Los Angeles Lakers -3.5", 
            "odds": -110,
            "confidence": 0.85,
            "tier_requirement": "pro",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    
    return {
        "status": "success",
        "bets": mock_bets,
        "user_tier": user_tier,
        "message": f"Mock YetAI bets for {user_tier} tier user - service unavailable"
    }

@app.options("/api/admin/yetai-bets/{bet_id}")
async def options_admin_delete_yetai_bet():
    """Handle CORS preflight for admin YetAI bet deletion"""
    return {}

@app.delete("/api/admin/yetai-bets/{bet_id}")
async def delete_yetai_bet(bet_id: str, current_user: dict = Depends(get_current_user)):
    """Delete YetAI bet (Admin only)"""
    # Check if user is admin (in real implementation)
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if is_service_available("yetai_bets_service"):
        try:
            yetai_service = get_service("yetai_bets_service")
            result = await yetai_service.delete_bet(bet_id)
            
            return {
                "status": "success",
                "message": f"YetAI bet {bet_id} deleted successfully",
                "result": result
            }
        except Exception as e:
            logger.error(f"Error deleting YetAI bet {bet_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete bet")
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "message": f"Mock deletion of YetAI bet {bet_id} - service unavailable"
    }

# Sports Betting API Endpoints
@app.options("/api/bets/place")
async def options_place_bet():
    """Handle CORS preflight for bet placement"""
    return {}

@app.post("/api/bets/place")
async def place_bet(bet_request: PlaceBetRequest, current_user: dict = Depends(get_current_user)):
    """Place a single sports bet"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.place_bet(
                user_id=current_user["user_id"],
                bet_type=bet_request.bet_type,
                selection=bet_request.selection,
                odds=bet_request.odds,
                amount=bet_request.amount,
                game_id=bet_request.game_id,
                home_team=bet_request.home_team,
                away_team=bet_request.away_team,
                sport=bet_request.sport,
                commence_time=bet_request.commence_time
            )
            return {"status": "success", "bet": result}
        except Exception as e:
            logger.error(f"Error placing bet: {e}")
            raise HTTPException(status_code=500, detail="Failed to place bet")
    
    # Mock response when service unavailable
    return {
        "status": "success",
        "bet": {
            "id": "mock_bet_123",
            "user_id": current_user["user_id"],
            "bet_type": bet_request.bet_type,
            "selection": bet_request.selection,
            "odds": bet_request.odds,
            "amount": bet_request.amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        "message": "Mock bet placed - bet service unavailable"
    }

@app.options("/api/bets/parlay")
async def options_place_parlay():
    """Handle CORS preflight for parlay placement"""
    return {}

@app.post("/api/bets/parlay")
async def place_parlay(parlay_request: PlaceParlayRequest, current_user: dict = Depends(get_current_user)):
    """Place a parlay bet with multiple legs"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.place_parlay(
                user_id=current_user["user_id"],
                amount=parlay_request.amount,
                legs=[leg.model_dump() for leg in parlay_request.legs]
            )
            return {"status": "success", "parlay": result}
        except Exception as e:
            logger.error(f"Error placing parlay: {e}")
            raise HTTPException(status_code=500, detail="Failed to place parlay")
    
    # Calculate mock total odds
    total_odds = 1
    for leg in parlay_request.legs:
        if leg.odds > 0:
            total_odds *= (leg.odds / 100 + 1)
        else:
            total_odds *= (100 / abs(leg.odds) + 1)
    
    american_odds = int((total_odds - 1) * 100) if total_odds >= 2 else int(-100 / (total_odds - 1))
    
    return {
        "status": "success", 
        "parlay": {
            "id": "mock_parlay_456",
            "user_id": current_user["user_id"],
            "amount": parlay_request.amount,
            "total_odds": american_odds,
            "legs": [leg.model_dump() for leg in parlay_request.legs],
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        "message": "Mock parlay placed - bet service unavailable"
    }

@app.options("/api/bets/parlays")
async def options_get_parlays():
    """Handle CORS preflight for getting parlays"""
    return {}

@app.get("/api/bets/parlays")
async def get_parlays(current_user: dict = Depends(get_current_user)):
    """Get user's parlay bets"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            parlays = await bet_service.get_user_parlays(current_user["user_id"])
            return {"status": "success", "parlays": parlays}
        except Exception as e:
            logger.error(f"Error fetching parlays: {e}")
    
    # Mock parlay data
    return {
        "status": "success",
        "parlays": [
            {
                "id": "mock_parlay_1",
                "amount": 50.0,
                "total_odds": 350,
                "status": "pending",
                "legs": [
                    {"selection": "Chiefs ML", "odds": -150},
                    {"selection": "Lakers -3.5", "odds": -110}
                ],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ],
        "message": "Mock parlays - bet service unavailable"
    }

@app.get("/api/bets/parlay/{parlay_id}")
async def get_parlay_details(parlay_id: str, current_user: dict = Depends(get_current_user)):
    """Get specific parlay details"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            parlay = await bet_service.get_parlay_by_id(parlay_id, current_user["user_id"])
            return {"status": "success", "parlay": parlay}
        except Exception as e:
            logger.error(f"Error fetching parlay {parlay_id}: {e}")
    
    # Mock parlay details
    return {
        "status": "success",
        "parlay": {
            "id": parlay_id,
            "amount": 50.0,
            "total_odds": 350,
            "status": "pending",
            "legs": [
                {
                    "selection": "Kansas City Chiefs ML",
                    "odds": -150,
                    "bet_type": "moneyline",
                    "game_id": "nfl_game_1"
                },
                {
                    "selection": "Los Angeles Lakers -3.5",
                    "odds": -110,
                    "bet_type": "spread", 
                    "game_id": "nba_game_1"
                }
            ],
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        "message": "Mock parlay details - bet service unavailable"
    }

@app.options("/api/bets/history")
async def options_bet_history():
    """Handle CORS preflight for bet history"""
    return {}

@app.post("/api/bets/history")
async def get_bet_history(query: BetHistoryQuery, current_user: dict = Depends(get_current_user)):
    """Get user bet history with filtering"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            history = await bet_service.get_bet_history(
                user_id=current_user["user_id"],
                status=query.status,
                bet_type=query.bet_type,
                start_date=query.start_date,
                end_date=query.end_date,
                offset=query.offset,
                limit=query.limit
            )
            return {"status": "success", "history": history}
        except Exception as e:
            logger.error(f"Error fetching bet history: {e}")
    
    # Mock bet history
    return {
        "status": "success",
        "history": [
            {
                "id": "bet_1",
                "bet_type": "moneyline",
                "selection": "Kansas City Chiefs",
                "odds": -150,
                "amount": 100.0,
                "status": query.status or "won",
                "created_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "id": "bet_2", 
                "bet_type": "spread",
                "selection": "Lakers -3.5",
                "odds": -110,
                "amount": 50.0,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ],
        "total": 2,
        "offset": query.offset,
        "limit": query.limit,
        "message": "Mock bet history - bet service unavailable"
    }

@app.options("/api/bets/stats")
async def options_bet_stats():
    """Handle CORS preflight for bet statistics"""
    return {}

@app.get("/api/bets/stats")
async def get_bet_stats(current_user: dict = Depends(get_current_user)):
    """Get comprehensive betting statistics for user"""
    if is_service_available("betting_analytics_service"):
        try:
            analytics_service = get_service("betting_analytics_service")
            stats = await analytics_service.get_user_stats(current_user["user_id"])
            return {"status": "success", "stats": stats}
        except Exception as e:
            logger.error(f"Error fetching bet stats: {e}")
    
    # Mock betting statistics
    return {
        "status": "success",
        "stats": {
            "total_bets": 25,
            "total_wagered": 1250.0,
            "total_winnings": 1375.0,
            "win_rate": 0.68,
            "roi": 0.10,
            "average_odds": -115,
            "favorite_sport": "NFL",
            "favorite_bet_type": "moneyline",
            "current_streak": {
                "type": "win",
                "count": 4
            },
            "monthly_summary": {
                "bets": 8,
                "wagered": 400.0,
                "winnings": 450.0,
                "roi": 0.125
            }
        },
        "message": "Mock betting statistics - analytics service unavailable"
    }

@app.options("/api/bets/share")
async def options_share_bet():
    """Handle CORS preflight for bet sharing"""
    return {}

@app.post("/api/bets/share")
async def share_bet(share_request: ShareBetRequest, current_user: dict = Depends(get_current_user)):
    """Share a bet with other users"""
    if is_service_available("bet_sharing_service_db"):
        try:
            sharing_service = get_service("bet_sharing_service_db")
            result = await sharing_service.share_bet(
                user_id=current_user["user_id"],
                bet_id=share_request.bet_id,
                message=share_request.message
            )
            return {"status": "success", "share": result}
        except Exception as e:
            logger.error(f"Error sharing bet: {e}")
            raise HTTPException(status_code=500, detail="Failed to share bet")
    
    # Mock sharing response
    return {
        "status": "success",
        "share": {
            "id": "share_123",
            "bet_id": share_request.bet_id,
            "user_id": current_user["user_id"],
            "message": share_request.message,
            "share_url": f"https://yetai.com/shared-bet/{share_request.bet_id}",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        "message": "Mock bet shared - sharing service unavailable"
    }

@app.options("/api/bets/shared")
async def options_get_shared_bets():
    """Handle CORS preflight for getting shared bets"""
    return {}

@app.get("/api/bets/shared")
async def get_shared_bets():
    """Get shared bets from other users"""
    if is_service_available("bet_sharing_service_db"):
        try:
            sharing_service = get_service("bet_sharing_service_db")
            shared_bets = await sharing_service.get_shared_bets()
            return {"status": "success", "shared_bets": shared_bets}
        except Exception as e:
            logger.error(f"Error fetching shared bets: {e}")
    
    # Mock shared bets
    return {
        "status": "success",
        "shared_bets": [
            {
                "id": "share_1",
                "bet_id": "bet_789",
                "user_id": "user_456",
                "username": "BettingPro23",
                "message": "Lock of the day! Chiefs are unstoppable.",
                "bet_details": {
                    "selection": "Kansas City Chiefs ML",
                    "odds": -150,
                    "amount": 200.0
                },
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ],
        "message": "Mock shared bets - sharing service unavailable"
    }

@app.options("/api/bets/shared/{share_id}")
async def options_delete_shared_bet():
    """Handle CORS preflight for deleting shared bet"""
    return {}

@app.delete("/api/bets/shared/{share_id}")
async def delete_shared_bet(share_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a shared bet"""
    if is_service_available("bet_sharing_service_db"):
        try:
            sharing_service = get_service("bet_sharing_service_db")
            await sharing_service.delete_shared_bet(share_id, current_user["user_id"])
            return {"status": "success", "message": f"Shared bet {share_id} deleted"}
        except Exception as e:
            logger.error(f"Error deleting shared bet {share_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete shared bet")
    
    # Mock deletion response
    return {
        "status": "success",
        "message": f"Mock deletion of shared bet {share_id} - sharing service unavailable"
    }

@app.options("/api/bets/{bet_id}")
async def options_delete_bet():
    """Handle CORS preflight for bet deletion"""
    return {}

@app.delete("/api/bets/{bet_id}")
async def delete_bet(bet_id: str, current_user: dict = Depends(get_current_user)):
    """Cancel/delete a bet"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.cancel_bet(bet_id, current_user["user_id"])
            return {"status": "success", "message": f"Bet {bet_id} cancelled", "result": result}
        except Exception as e:
            logger.error(f"Error cancelling bet {bet_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to cancel bet")
    
    # Mock cancellation response
    return {
        "status": "success",
        "message": f"Mock cancellation of bet {bet_id} - bet service unavailable"
    }

@app.options("/api/bets/simulate")
async def options_simulate_bet():
    """Handle CORS preflight for bet simulation"""
    return {}

@app.post("/api/bets/simulate")
async def simulate_bet():
    """Simulate bet results for development/testing"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            result = await bet_service.simulate_bet_outcome()
            return {"status": "success", "simulation": result}
        except Exception as e:
            logger.error(f"Error simulating bet: {e}")
    
    # Mock simulation
    import random
    return {
        "status": "success",
        "simulation": {
            "outcome": random.choice(["win", "loss", "push"]),
            "confidence": round(random.uniform(0.5, 0.95), 2),
            "payout": round(random.uniform(50, 500), 2) if random.choice([True, False]) else 0,
            "message": "Simulated bet outcome for testing"
        },
        "message": "Mock bet simulation - bet service unavailable"
    }

# Fantasy Sports API Endpoints
@app.options("/api/fantasy/accounts")
async def options_fantasy_accounts():
    """Handle CORS preflight for fantasy accounts"""
    return {}

@app.get("/api/fantasy/accounts")
async def get_fantasy_accounts(current_user: dict = Depends(get_current_user)):
    """Get connected fantasy accounts"""
    if is_service_available("fantasy_pipeline"):
        try:
            fantasy_service = get_service("fantasy_pipeline")
            accounts = await fantasy_service.get_user_accounts(current_user["user_id"])
            return {"status": "success", "accounts": accounts}
        except Exception as e:
            logger.error(f"Error fetching fantasy accounts: {e}")
    
    # Mock fantasy accounts
    return {
        "status": "success",
        "accounts": [
            {
                "platform": "sleeper",
                "username": "YetAI_User",
                "user_id": "sleeper_123",
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "status": "active"
            }
        ],
        "message": "Mock fantasy accounts - fantasy service unavailable"
    }

@app.options("/api/fantasy/leagues")
async def options_fantasy_leagues():
    """Handle CORS preflight for fantasy leagues"""
    return {}

@app.get("/api/fantasy/leagues")
async def get_fantasy_leagues(current_user: dict = Depends(get_current_user)):
    """Get fantasy leagues for user"""
    if is_service_available("fantasy_pipeline"):
        try:
            fantasy_service = get_service("fantasy_pipeline")
            leagues = await fantasy_service.get_user_leagues(current_user["user_id"])
            return {"status": "success", "leagues": leagues}
        except Exception as e:
            logger.error(f"Error fetching fantasy leagues: {e}")
    
    # Mock fantasy leagues
    return {
        "status": "success",
        "leagues": [
            {
                "league_id": "league_123",
                "name": "Championship League",
                "platform": "sleeper",
                "sport": "nfl",
                "season": "2025",
                "total_teams": 12,
                "scoring_type": "ppr",
                "status": "active"
            }
        ],
        "message": "Mock fantasy leagues - fantasy service unavailable"
    }

@app.options("/api/fantasy/connect")
async def options_fantasy_connect():
    """Handle CORS preflight for fantasy platform connection"""
    return {}

@app.post("/api/fantasy/connect")
async def connect_fantasy_platform(connect_request: FantasyConnectRequest, current_user: dict = Depends(get_current_user)):
    """Connect to a fantasy platform (Sleeper, ESPN, etc.)"""
    if is_service_available("fantasy_pipeline"):
        try:
            fantasy_service = get_service("fantasy_pipeline")
            result = await fantasy_service.connect_platform(
                user_id=current_user["user_id"],
                platform=connect_request.platform,
                credentials=connect_request.credentials
            )
            return {"status": "success", "connection": result}
        except Exception as e:
            logger.error(f"Error connecting to {connect_request.platform}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to connect to {connect_request.platform}")
    
    # Mock connection response
    return {
        "status": "success",
        "connection": {
            "platform": connect_request.platform,
            "status": "connected",
            "user_id": f"{connect_request.platform}_user_456",
            "connected_at": datetime.now(timezone.utc).isoformat()
        },
        "message": f"Mock connection to {connect_request.platform} - fantasy service unavailable"
    }

@app.options("/api/fantasy/roster/{league_id}")
async def options_fantasy_roster():
    """Handle CORS preflight for fantasy roster"""
    return {}

@app.get("/api/fantasy/roster/{league_id}")
async def get_fantasy_roster(league_id: str, current_user: dict = Depends(get_current_user)):
    """Get fantasy roster for a specific league"""
    if is_service_available("fantasy_pipeline"):
        try:
            fantasy_service = get_service("fantasy_pipeline")
            roster = await fantasy_service.get_league_roster(league_id, current_user["user_id"])
            return {"status": "success", "roster": roster}
        except Exception as e:
            logger.error(f"Error fetching roster for league {league_id}: {e}")
    
    # Mock roster data
    return {
        "status": "success",
        "roster": {
            "league_id": league_id,
            "team_name": "YetAI Champions",
            "players": [
                {
                    "player_id": "player_1",
                    "name": "Josh Allen",
                    "position": "QB",
                    "team": "BUF",
                    "status": "active"
                },
                {
                    "player_id": "player_2", 
                    "name": "Christian McCaffrey",
                    "position": "RB",
                    "team": "SF",
                    "status": "active"
                }
            ]
        },
        "message": "Mock fantasy roster - fantasy service unavailable"
    }

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
        "projections": [
            {
                "player_id": "player_1",
                "name": "Josh Allen",
                "position": "QB",
                "team": "BUF",
                "projected_points": 24.5,
                "confidence": 0.82
            },
            {
                "player_id": "player_2",
                "name": "Christian McCaffrey", 
                "position": "RB",
                "team": "SF",
                "projected_points": 18.3,
                "confidence": 0.75
            }
        ],
        "message": "Mock fantasy projections - fantasy service unavailable"
    }

# Odds and Markets API Endpoints
@app.options("/api/odds/americanfootball_nfl")
async def options_nfl_odds():
    """Handle CORS preflight for NFL odds"""
    return {}

@app.get("/api/odds/americanfootball_nfl")
async def get_nfl_odds():
    """Get NFL odds directly"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("americanfootball_nfl")
                return {"status": "success", "data": games}
        except Exception as e:
            logger.error(f"Error fetching NFL odds: {e}")
            # Fall through to mock data
    
    # Return mock NFL data
    return {
        "status": "success",
        "data": [],
        "message": f"Mock NFL odds - Running in {settings.ENVIRONMENT} mode"
    }

@app.options("/api/odds/basketball_nba") 
async def options_nba_odds():
    """Handle CORS preflight for NBA odds"""
    return {}

@app.get("/api/odds/basketball_nba")
async def get_nba_odds():
    """Get NBA odds directly"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("basketball_nba")
                return {"status": "success", "data": games}
        except Exception as e:
            logger.error(f"Error fetching NBA odds: {e}")
    
    return {
        "status": "success", 
        "data": [],
        "message": f"Mock NBA odds - Running in {settings.ENVIRONMENT} mode"
    }

@app.options("/api/odds/baseball_mlb")
async def options_mlb_odds():
    """Handle CORS preflight for MLB odds"""
    return {}

@app.get("/api/odds/baseball_mlb")
async def get_mlb_odds():
    """Get MLB odds directly"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("baseball_mlb")
                return {"status": "success", "data": games}
        except Exception as e:
            logger.error(f"Error fetching MLB odds: {e}")
    
    return {
        "status": "success",
        "data": [], 
        "message": f"Mock MLB odds - Running in {settings.ENVIRONMENT} mode"
    }

@app.options("/api/odds/icehockey_nhl")
async def options_nhl_odds():
    """Handle CORS preflight for NHL odds"""
    return {}

@app.get("/api/odds/icehockey_nhl")
async def get_nhl_odds():
    """Get NHL (Ice Hockey) odds"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("icehockey_nhl")
                return {"status": "success", "data": games}
        except Exception as e:
            logger.error(f"Error fetching NHL odds: {e}")
    
    return {
        "status": "success",
        "data": [],
        "message": f"Mock NHL odds - Running in {settings.ENVIRONMENT} mode"
    }

@app.options("/api/odds/hockey")
async def options_hockey_odds():
    """Handle CORS preflight for hockey odds"""
    return {}

@app.get("/api/odds/hockey")
async def get_hockey_odds():
    """Get Hockey odds (alias for NHL)"""
    # Redirect to NHL odds
    return await get_nhl_odds()

@app.get("/api/odds/nfl")
async def get_nfl_odds_legacy():
    """Get NFL odds (legacy endpoint)"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import OddsAPIService
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("americanfootball_nfl")
                return {"status": "success", "odds": games}
        except Exception as e:
            logger.error(f"Error fetching NFL odds: {e}")
    
    return {
        "status": "success",
        "odds": [],
        "message": "Mock data - Odds API not configured"
    }

@app.get("/api/odds/popular")
async def get_popular_sports_odds():
    """Get odds for popular sports (NFL, NBA, MLB, NHL)"""
    if settings.ODDS_API_KEY and is_service_available("sports_pipeline"):
        try:
            from app.services.odds_api_service import get_popular_sports_odds
            games = await get_popular_sports_odds()
            return {"status": "success", "data": games}
        except Exception as e:
            logger.error(f"Error fetching popular sports odds: {e}")
    
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
            }
        ],
        "message": f"Mock data - Running in {settings.ENVIRONMENT} mode"
    }

# Parlay-specific endpoints
@app.options("/api/parlays/markets")
async def options_parlay_markets():
    """Handle CORS preflight for parlay markets"""
    return {}

@app.get("/api/parlays/markets")
async def get_parlay_markets(sport: Optional[str] = None):
    """Get available markets for parlay betting"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            markets = await bet_service.get_parlay_markets(sport=sport)
            return {"status": "success", "markets": markets}
        except Exception as e:
            logger.error(f"Error fetching parlay markets: {e}")
    
    # Mock parlay markets
    markets = [
        {
            "sport": "nfl",
            "name": "NFL",
            "markets": ["h2h", "spreads", "totals", "props"]
        },
        {
            "sport": "nba", 
            "name": "NBA",
            "markets": ["h2h", "spreads", "totals", "props"]
        }
    ]
    
    # Add NHL if specifically requested or show all
    if sport == "icehockey_nhl" or not sport:
        markets.append({
            "sport": "icehockey_nhl",
            "name": "NHL", 
            "markets": ["h2h", "spreads", "totals"]
        })
    
    # Filter by sport if specified
    if sport:
        markets = [m for m in markets if m["sport"] == sport]
    
    return {
        "status": "success",
        "markets": markets,
        "message": "Mock parlay markets - bet service unavailable"
    }

@app.options("/api/parlays/popular")
async def options_popular_parlays():
    """Handle CORS preflight for popular parlays"""
    return {}

@app.get("/api/parlays/popular")
async def get_popular_parlays():
    """Get popular parlay combinations"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            parlays = await bet_service.get_popular_parlays()
            return {"status": "success", "parlays": parlays}
        except Exception as e:
            logger.error(f"Error fetching popular parlays: {e}")
    
    # Mock popular parlays including hockey
    return {
        "status": "success",
        "parlays": [
            {
                "id": "popular_1",
                "name": "NFL Sunday Special",
                "legs": [
                    {"selection": "Chiefs ML", "odds": -150, "sport": "nfl"},
                    {"selection": "Lakers -3.5", "odds": -110, "sport": "nba"}
                ],
                "total_odds": 250,
                "popularity_score": 0.85
            },
            {
                "id": "popular_2", 
                "name": "Hockey Hat Trick",
                "legs": [
                    {"selection": "Rangers ML", "odds": -130, "sport": "icehockey_nhl"},
                    {"selection": "Bruins Over 6.5", "odds": -105, "sport": "icehockey_nhl"},
                    {"selection": "McDavid Anytime Goal", "odds": 180, "sport": "icehockey_nhl"}
                ],
                "total_odds": 650,
                "popularity_score": 0.72
            }
        ],
        "message": "Mock popular parlays - bet service unavailable"
    }

# Profile and Status endpoints
@app.options("/api/profile/sports")
async def options_profile_sports():
    """Handle CORS preflight for user sports preferences"""
    return {}

@app.get("/api/profile/sports")
async def get_profile_sports(current_user: dict = Depends(get_current_user)):
    """Get user's sports preferences and settings"""
    if is_service_available("auth_service"):
        try:
            auth_service = get_service("auth_service")
            profile = await auth_service.get_user_profile(current_user["user_id"])
            return {
                "status": "success",
                "sports": profile.get("preferred_sports", []),
                "favorite_teams": profile.get("favorite_teams", []),
                "notification_settings": profile.get("notification_settings", {})
            }
        except Exception as e:
            logger.error(f"Error fetching user sports profile: {e}")
    
    # Mock sports preferences
    return {
        "status": "success",
        "sports": ["nfl", "nba", "icehockey_nhl"],
        "favorite_teams": [
            {"sport": "nfl", "team": "Kansas City Chiefs"},
            {"sport": "nba", "team": "Los Angeles Lakers"},
            {"sport": "icehockey_nhl", "team": "New York Rangers"}
        ],
        "notification_settings": {
            "game_updates": True,
            "bet_results": True,
            "yetai_predictions": True
        },
        "message": "Mock sports preferences - auth service unavailable"
    }

@app.options("/api/profile/status")
async def options_profile_status():
    """Handle CORS preflight for user profile status"""
    return {}

@app.get("/api/profile/status")
async def get_profile_status(current_user: dict = Depends(get_current_user)):
    """Get comprehensive user profile status"""
    if is_service_available("auth_service"):
        try:
            auth_service = get_service("auth_service")
            status_info = await auth_service.get_user_status(current_user["user_id"])
            return {"status": "success", "profile_status": status_info}
        except Exception as e:
            logger.error(f"Error fetching user profile status: {e}")
    
    # Mock profile status
    return {
        "status": "success",
        "profile_status": {
            "user_id": current_user["user_id"],
            "subscription_tier": current_user.get("subscription_tier", "free"),
            "account_status": "active",
            "profile_completion": 0.85,
            "last_activity": datetime.now(timezone.utc).isoformat(),
            "stats": {
                "total_bets": 25,
                "win_rate": 0.68,
                "favorite_sport": "nfl"
            },
            "connected_platforms": ["sleeper"],
            "notification_preferences": {
                "email": True,
                "push": True
            }
        },
        "message": "Mock profile status - auth service unavailable"
    }

# Live betting endpoints
@app.options("/api/live-bets/markets")
async def options_live_markets():
    """Handle CORS preflight for live markets"""
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
        "message": "Mock live markets - bet service unavailable"
    }

@app.options("/api/live-bets/active")
async def options_active_live_bets():
    """Handle CORS preflight for active live bets"""
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
        "message": "Mock active live bets - bet service unavailable"
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
    
    return {
        "status": "success",
        "response": {
            "role": "assistant",
            "content": f"I'm currently in {settings.ENVIRONMENT} mode with limited AI capabilities. Here's some general sports betting advice: Always bet responsibly and never wager more than you can afford to lose!",
            "timestamp": datetime.now(timezone.utc).isoformat()
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

# Comprehensive endpoint health check
@app.get("/api/endpoints/health")
async def endpoint_health_check():
    """Comprehensive health check for all API endpoints"""
    
    endpoint_categories = {
        "Core API": {
            "endpoints": ["/health", "/", "/api/status"],
            "operational": True
        },
        "Authentication": {
            "endpoints": ["/api/auth/status", "/api/auth/register", "/api/auth/login", "/api/auth/me"],
            "operational": is_service_available("auth_service")
        },
        "YetAI Bets": {
            "endpoints": ["/api/yetai-bets", "/api/admin/yetai-bets/{bet_id}"],
            "operational": is_service_available("yetai_bets_service")
        },
        "Sports Betting": {
            "endpoints": [
                "/api/bets/place", "/api/bets/parlay", "/api/bets/parlays", 
                "/api/bets/history", "/api/bets/stats", "/api/bets/share",
                "/api/bets/shared", "/api/bets/simulate"
            ],
            "operational": is_service_available("bet_service")
        },
        "Fantasy Sports": {
            "endpoints": [
                "/api/fantasy/accounts", "/api/fantasy/leagues", 
                "/api/fantasy/connect", "/api/fantasy/projections"
            ],
            "operational": is_service_available("fantasy_pipeline")
        },
        "Odds & Markets": {
            "endpoints": [
                "/api/odds/americanfootball_nfl", "/api/odds/basketball_nba",
                "/api/odds/baseball_mlb", "/api/odds/icehockey_nhl", "/api/odds/popular"
            ],
            "operational": is_service_available("sports_pipeline")
        },
        "Parlays": {
            "endpoints": ["/api/parlays/markets", "/api/parlays/popular"],
            "operational": is_service_available("bet_service")
        },
        "Profile & Status": {
            "endpoints": ["/api/profile/sports", "/api/profile/status"],
            "operational": is_service_available("auth_service")
        },
        "Live Betting": {
            "endpoints": ["/api/live-bets/markets", "/api/live-bets/active"],
            "operational": is_service_available("bet_service")
        },
        "AI Chat": {
            "endpoints": ["/api/chat/message", "/api/chat/suggestions"],
            "operational": is_service_available("ai_chat_service")
        },
        "Sports Data": {
            "endpoints": ["/api/games/nfl"],
            "operational": is_service_available("sports_pipeline")
        }
    }
    
    operational_count = sum(1 for cat in endpoint_categories.values() if cat["operational"])
    total_count = len(endpoint_categories)
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "categories": endpoint_categories,
        "summary": {
            "operational_categories": operational_count,
            "total_categories": total_count,
            "health_percentage": round((operational_count / total_count) * 100, 1)
        },
        "services": service_loader.get_status(),
        "environment": settings.ENVIRONMENT
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