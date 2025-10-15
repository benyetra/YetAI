"""
Environment-aware FastAPI application for YetAI Sports Betting MVP
Consolidates development and production functionality into a single file
Version: 1.0.1
"""

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any

# Import core configuration and service loader
from app.core.config import settings
from app.core.service_loader import (
    initialize_services,
    get_service,
    is_service_available,
)
from app.core.database import get_db, SessionLocal
from sqlalchemy.orm import Session

# Import unified bet service
from app.services.simple_unified_bet_service import simple_unified_bet_service

# Import live betting service
from app.services.live_betting_service_db import LiveBettingServiceDB

# Initialize service instances
live_betting_service = LiveBettingServiceDB()

# Import bet scheduler service
from app.services.bet_scheduler_service import (
    bet_scheduler,
    init_scheduler,
    cleanup_scheduler,
)
from app.services.unified_bet_verification_service import (
    unified_bet_verification_service,
)

# Import live betting models
from app.models.live_bet_models import PlaceLiveBetRequest, LiveBetResponse
from app.models.bet_models import CreateYetAIBetRequest, CreateParlayBetRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import Google OAuth service (optional - gracefully handle if dependencies are missing)
try:
    from app.services.google_oauth_service import google_oauth_service

    GOOGLE_OAUTH_AVAILABLE = True
    logger.info("Google OAuth service initialized successfully")
except Exception as e:
    logger.warning(f"Google OAuth service not available: {e}")
    google_oauth_service = None
    GOOGLE_OAUTH_AVAILABLE = False

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
    yetai_bet_id: Optional[str] = None  # Link to YetAI bet for tracking
    # Player prop fields
    player_name: Optional[str] = None  # For player prop bets
    prop_market: Optional[str] = None  # Market key (e.g., player_pass_tds)
    prop_line: Optional[float] = None  # The line/point value
    prop_selection: Optional[str] = None  # 'over' or 'under'


class ParlayLeg(BaseModel):
    bet_type: str
    selection: str
    odds: float
    game_id: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    sport: Optional[str] = None
    commence_time: Optional[str] = None
    # Player prop fields
    player_name: Optional[str] = None
    prop_market: Optional[str] = None
    prop_line: Optional[float] = None
    prop_selection: Optional[str] = None


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
    """Extract user from JWT token"""
    try:
        token = credentials.credentials

        # Basic validation
        invalid_token_value = (
            "invalid"  # nosec B105 - this is a test token value, not a real password
        )
        if not token or token == invalid_token_value:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Decode JWT token (without signature verification for now)
        import jwt

        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("sub")

            if user_id:
                # Convert user_id to integer if it's a string
                user_id = int(user_id) if isinstance(user_id, str) else user_id
                return {
                    "user_id": user_id,
                    "email": "user@example.com",
                    "subscription_tier": "pro",
                }
            else:
                raise HTTPException(status_code=401, detail="Invalid token payload")

        except (jwt.InvalidTokenError, ValueError) as e:
            # Fallback to mock user for development tokens
            logger.warning(f"JWT decode failed, using mock user: {e}")
            return {
                "user_id": 123,  # Mock user as integer
                "email": "user@example.com",
                "subscription_tier": "pro",
            }

    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def require_admin(current_user: dict = Depends(get_current_user)):
    """Require admin privileges"""
    # Check if user has admin privileges from the database
    if is_service_available("auth_service"):
        auth_service = get_service("auth_service")
        try:
            user_data = await auth_service.get_user_by_id(
                current_user.get("id") or current_user.get("user_id")
            )
            if not user_data or not user_data.get("is_admin", False):
                raise HTTPException(status_code=403, detail="Admin privileges required")
            return user_data
        except Exception as e:
            logger.error(f"Error checking admin privileges: {e}")
            raise HTTPException(status_code=403, detail="Admin privileges required")
    else:
        # Fallback: assume user 8 is admin for development
        if (current_user.get("id") or current_user.get("user_id")) == 8:
            return current_user
        raise HTTPException(status_code=403, detail="Admin privileges required")


def calculate_realistic_trade_value(player: Dict[str, Any]) -> float:
    """Calculate realistic player trade value based on Sleeper data"""
    position = player.get("position", "UNKNOWN")
    age = player.get("age", 27)
    team = player.get("team", "")

    # Base values by position (realistic ranges from trade_analyzer_service.py)
    base_values = {
        "QB": (20.0, 45.0),  # QB range 20-45
        "RB": (15.0, 40.0),  # RB range 15-40
        "WR": (12.0, 38.0),  # WR range 12-38
        "TE": (8.0, 25.0),  # TE range 8-25
        "K": (2.0, 6.0),  # K range 2-6
        "DEF": (3.0, 8.0),  # DEF range 3-8
    }

    min_val, max_val = base_values.get(position, (8.0, 15.0))

    # Age-based value adjustment (handle None age)
    age = age or 27  # Default to 27 if None
    if age <= 24:
        age_multiplier = 1.1  # Young player bonus
    elif age <= 27:
        age_multiplier = 1.0  # Prime years
    elif age <= 30:
        age_multiplier = 0.95  # Slight decline
    else:
        age_multiplier = 0.8  # Aging player discount

    # Team quality impact (simplified based on team name)
    team_multiplier = 1.0
    if team in ["KC", "BUF", "DAL", "SF", "PHI", "MIA", "LAR"]:
        team_multiplier = 1.05  # Good offense teams
    elif team in ["WAS", "CHI", "NYG", "CAR"]:
        team_multiplier = 0.95  # Weaker offense teams

    # Calculate final value with some variance
    import random

    base_value = random.uniform(min_val, max_val)
    final_value = base_value * age_multiplier * team_multiplier

    return round(final_value, 1)


# Environment-aware CORS configuration
def get_cors_origins():
    """Get CORS origins based on environment using centralized configuration"""
    return settings.get_frontend_urls()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info(
        f"🚀 Starting YetAI Sports Betting MVP - {settings.ENVIRONMENT.upper()} Environment"
    )

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
            if hasattr(scheduler, "start"):
                await scheduler.start()
                logger.info("✅ Scheduler service started")
        except Exception as e:
            logger.warning(f"⚠️  Scheduler initialization failed: {e}")

    # Start the bet verification scheduler
    try:
        init_scheduler()
        logger.info("✅ Bet verification scheduler started")
    except Exception as e:
        logger.warning(f"⚠️  Bet verification scheduler initialization failed: {e}")

    # Sync upcoming games to database on startup (non-blocking)
    if settings.ODDS_API_KEY:

        async def _background_game_sync():
            """Run initial game sync in background to not block startup"""
            try:
                from app.services.games_sync_service import run_games_sync

                logger.info("🔄 Starting background game sync...")
                result = await run_games_sync()
                logger.info(
                    f"✅ Initial game sync: {result.get('total_games_fetched', 0)} fetched, "
                    f"{result.get('total_games_created', 0)} created, "
                    f"{result.get('total_games_updated', 0)} updated"
                )
            except Exception as e:
                logger.warning(f"⚠️  Initial game sync failed: {e}")

        # Start sync in background - don't wait for it
        asyncio.create_task(_background_game_sync())
        logger.info("🔄 Game sync started in background")

    # Log service summary
    available_services = [
        name
        for name in service_loader.get_status()
        if service_loader.is_available(name)
    ]
    logger.info(
        f"✅ Services online: {len(available_services)}/{len(service_loader.get_status())}"
    )

    yield

    # Shutdown
    logger.info("🛑 Shutting down YetAI Sports Betting MVP")

    # Cleanup scheduler if available
    if is_service_available("scheduler_service"):
        try:
            scheduler = get_service("scheduler_service")
            if hasattr(scheduler, "stop"):
                await scheduler.stop()
                logger.info("✅ Scheduler service stopped")
        except Exception as e:
            logger.warning(f"⚠️  Scheduler cleanup failed: {e}")

    # Stop the bet verification scheduler
    try:
        cleanup_scheduler()
        logger.info("✅ Bet verification scheduler stopped")
    except Exception as e:
        logger.warning(f"⚠️  Bet verification scheduler cleanup failed: {e}")


# Create FastAPI app
app = FastAPI(
    title="YetAI Sports Betting MVP",
    description=f"AI-Powered Sports Betting Platform - {settings.ENVIRONMENT.title()} Environment",
    version="1.2.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Add CORS middleware with environment-aware origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount static files for avatars
# Create uploads directory if it doesn't exist and mount it
uploads_dir = Path(__file__).parent / "uploads"
uploads_dir.mkdir(exist_ok=True)
(uploads_dir / "avatars").mkdir(exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


# Debug endpoint to check avatar files
@app.get("/debug/avatar/{user_id}")
async def debug_avatar(user_id: int):
    """Debug endpoint to check avatar files and paths"""
    uploads_dir = Path(__file__).parent / "uploads" / "avatars"
    logger.info(f"Checking avatar directory: {uploads_dir}")
    logger.info(f"Directory exists: {uploads_dir.exists()}")

    if uploads_dir.exists():
        files = list(uploads_dir.glob(f"{user_id}_*.jpg"))
        logger.info(f"Found files for user {user_id}: {files}")
        all_files = list(uploads_dir.glob("*.jpg"))
        return {
            "uploads_dir": str(uploads_dir),
            "exists": uploads_dir.exists(),
            "files": [str(f) for f in files],
            "user_files": [f.name for f in files],
            "all_files": [f.name for f in all_files],
            "static_mount_dir": str(Path(__file__).parent / "uploads"),
        }
    else:
        return {
            "uploads_dir": str(uploads_dir),
            "exists": False,
            "error": "Directory does not exist",
        }


# Alternative avatar serving endpoint for debugging
@app.get("/api/serve-avatar/{filename}")
async def serve_avatar_debug(filename: str):
    """Alternative avatar serving for debugging"""
    from fastapi.responses import FileResponse

    uploads_dir = Path(__file__).parent / "uploads" / "avatars"
    file_path = uploads_dir / filename

    logger.info(f"Trying to serve: {file_path}")
    logger.info(f"File exists: {file_path.exists()}")

    if file_path.exists() and file_path.is_file():
        return FileResponse(
            path=str(file_path),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    else:
        raise HTTPException(status_code=404, detail="Avatar not found")


# Debug endpoint to check S3 configuration
@app.get("/debug/s3-config")
async def debug_s3_config():
    """Debug endpoint to check S3 configuration status"""
    import os
    from app.services.avatar_service import avatar_service

    # Check if boto3 can be imported
    boto3_available = False
    boto3_error = None
    try:
        import boto3

        boto3_available = True
    except ImportError as e:
        boto3_error = str(e)

    return {
        "s3_enabled": avatar_service.use_s3,
        "boto3_available": boto3_available,
        "boto3_error": boto3_error,
        "has_access_key": bool(os.getenv("AWS_ACCESS_KEY_ID")),
        "has_secret_key": bool(os.getenv("AWS_SECRET_ACCESS_KEY")),
        "has_bucket": bool(os.getenv("AWS_S3_BUCKET_NAME")),
        "bucket_name": (
            os.getenv("AWS_S3_BUCKET_NAME", "").split("/")[0]
            if os.getenv("AWS_S3_BUCKET_NAME")
            else None
        ),
        "region": os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        "storage_type": "S3" if avatar_service.use_s3 else "Local Filesystem",
        "storage_path": (
            str(avatar_service.base_path)
            if hasattr(avatar_service, "base_path")
            else None
        ),
    }


# Health and status endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway/deployment monitoring"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": service_loader.get_status(),
        "google_oauth_available": GOOGLE_OAUTH_AVAILABLE,
        "google_client_id_set": bool(settings.GOOGLE_CLIENT_ID),
        "google_client_secret_set": bool(settings.GOOGLE_CLIENT_SECRET),
    }


@app.options("/api/platform/stats")
async def options_platform_stats():
    """Handle CORS preflight for platform stats endpoint"""
    return {}


@app.get("/api/platform/stats")
async def get_platform_statistics(db: Session = Depends(get_db)):
    """Get platform-wide statistics for display on login page"""
    from app.models.database_models import User, YetAIBet
    from sqlalchemy import func, and_
    from datetime import timedelta

    try:
        # Get total registered users (excluding hidden users)
        total_users = (
            db.query(func.count(User.id)).filter(User.is_hidden == False).scalar() or 0
        )
        logger.info(
            f"Platform stats: Found {total_users} total users (excluding hidden)"
        )

        # Get total winnings from YetAI bets (won bets only)
        # Calculate based on $100 wager per bet
        won_bets = db.query(YetAIBet).filter(YetAIBet.result == "won").all()

        total_winnings = 0
        for bet in won_bets:
            # Calculate profit from $100 wager using American odds
            if bet.odds > 0:
                profit = 100 * (bet.odds / 100)
            else:
                profit = 100 * (100 / abs(bet.odds))
            total_winnings += profit

        # Get 30-day performance
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        # Last 30 days bets
        last_30_days_bets = (
            db.query(YetAIBet)
            .filter(
                and_(
                    YetAIBet.settled_at >= thirty_days_ago,
                    YetAIBet.result.in_(["won", "lost"]),
                )
            )
            .all()
        )

        # Last 7 days bets (for week-over-week comparison)
        last_7_days_bets = (
            db.query(YetAIBet)
            .filter(
                and_(
                    YetAIBet.settled_at >= seven_days_ago,
                    YetAIBet.result.in_(["won", "lost"]),
                )
            )
            .all()
        )

        # Calculate 30-day performance
        wins_30d = sum(1 for bet in last_30_days_bets if bet.result == "won")
        total_30d = len(last_30_days_bets)
        win_rate_30d = (wins_30d / total_30d * 100) if total_30d > 0 else 0

        # Calculate profit/loss for 30 days
        profit_30d = 0
        for bet in last_30_days_bets:
            if bet.result == "won":
                if bet.odds > 0:
                    profit_30d += 100 * (bet.odds / 100)
                else:
                    profit_30d += 100 * (100 / abs(bet.odds))
            else:
                profit_30d -= 100

        # Calculate 7-day performance for comparison
        wins_7d = sum(1 for bet in last_7_days_bets if bet.result == "won")
        total_7d = len(last_7_days_bets)
        win_rate_7d = (wins_7d / total_7d * 100) if total_7d > 0 else 0

        profit_7d = 0
        for bet in last_7_days_bets:
            if bet.result == "won":
                if bet.odds > 0:
                    profit_7d += 100 * (bet.odds / 100)
                else:
                    profit_7d += 100 * (100 / abs(bet.odds))
            else:
                profit_7d -= 100

        # Calculate week-over-week percentage change
        # Compare last 7 days to previous 7 days (8-14 days ago)
        fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
        previous_7_days_bets = (
            db.query(YetAIBet)
            .filter(
                and_(
                    YetAIBet.settled_at >= fourteen_days_ago,
                    YetAIBet.settled_at < seven_days_ago,
                    YetAIBet.result.in_(["won", "lost"]),
                )
            )
            .all()
        )

        profit_prev_7d = 0
        for bet in previous_7_days_bets:
            if bet.result == "won":
                if bet.odds > 0:
                    profit_prev_7d += 100 * (bet.odds / 100)
                else:
                    profit_prev_7d += 100 * (100 / abs(bet.odds))
            else:
                profit_prev_7d -= 100

        # Calculate week-over-week change
        if profit_prev_7d != 0:
            wow_change = ((profit_7d - profit_prev_7d) / abs(profit_prev_7d)) * 100
        elif profit_7d > 0:
            wow_change = 100  # 100% increase from 0
        else:
            wow_change = 0

        # Get recent user avatars (latest 3 users with avatars, excluding hidden users)
        recent_users = (
            db.query(User)
            .filter(and_(User.avatar_url.isnot(None), User.is_hidden == False))
            .order_by(User.created_at.desc())
            .limit(3)
            .all()
        )

        user_avatars = []
        for user in recent_users:
            if user.avatar_url:
                user_avatars.append(
                    {
                        "url": user.avatar_url,
                        "name": f"{user.first_name or ''} {user.last_name or ''}".strip()
                        or user.username,
                    }
                )

        result = {
            "status": "success",
            "data": {
                "total_users": total_users,
                "total_winnings": round(total_winnings, 2),
                "performance_30d": {
                    "win_rate": round(win_rate_30d, 1),
                    "profit": round(profit_30d, 2),
                    "total_bets": total_30d,
                    "wins": wins_30d,
                    "losses": total_30d - wins_30d,
                },
                "performance_7d": {
                    "win_rate": round(win_rate_7d, 1),
                    "profit": round(profit_7d, 2),
                    "wow_change": round(wow_change, 1),
                },
                "user_avatars": user_avatars,
            },
        }
        logger.info(
            f"Platform stats response: users={total_users}, winnings={total_winnings}, "
            f"30d_bets={total_30d}, avatars={len(user_avatars)}"
        )
        return result

    except Exception as e:
        logger.error(f"Error fetching platform statistics: {e}")
        return {
            "status": "error",
            "message": str(e),
            "data": {
                "total_users": 0,
                "total_winnings": 0,
                "performance_30d": {
                    "win_rate": 0,
                    "profit": 0,
                    "total_bets": 0,
                    "wins": 0,
                    "losses": 0,
                },
                "performance_7d": {"win_rate": 0, "profit": 0, "wow_change": 0},
                "user_avatars": [],
            },
        }


@app.get("/api/test/smtp")
async def test_smtp_connection():
    """Test SMTP connection to debug email issues"""
    import smtplib
    import socket

    smtp_host = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")

    results = {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user_set": bool(smtp_user),
        "tests": {},
    }

    # Test DNS
    try:
        ip = socket.gethostbyname(smtp_host)
        results["tests"]["dns"] = {"success": True, "ip": ip}
    except Exception as e:
        results["tests"]["dns"] = {"success": False, "error": str(e)}
        return results

    # Test TCP connection
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((smtp_host, smtp_port))
        sock.close()
        results["tests"]["tcp"] = {"success": True}
    except Exception as e:
        results["tests"]["tcp"] = {"success": False, "error": str(e)}
        return results

    # Test SMTP handshake
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            results["tests"]["smtp_handshake"] = {"success": True}
    except Exception as e:
        results["tests"]["smtp_handshake"] = {"success": False, "error": str(e)}

    return results


# User endpoints that frontend expects
@app.options("/api/user/performance")
async def options_user_performance():
    """Handle CORS preflight for user performance endpoint"""
    return {}


@app.get("/api/user/performance")
async def get_user_performance(current_user: dict = Depends(get_current_user)):
    """Get user performance metrics based on real bet data"""
    try:
        user_id = current_user.get("id") or current_user.get("user_id")

        # Use betting analytics service to get real user stats
        analytics_service = get_service("betting_analytics_service")
        if not analytics_service:
            raise Exception("Betting analytics service not available")
        stats = await analytics_service.get_user_stats(user_id)

        # Get trend data from betting analytics
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            trends = await analytics_service._get_performance_trend(user_id, db)
        finally:
            db.close()

        # Calculate weekly and monthly changes
        monthly_summary = stats.get("monthly_summary", {})
        weekly_bet_change = trends.get("recent_period", {}).get("total_bets", 0)
        accuracy_change = trends.get("win_rate_change", 0)
        profit_change = trends.get("profit_change", 0)

        # Format the response for the dashboard
        personal_stats = {
            "predictions_made": stats["total_bets"],
            "accuracy_rate": round(stats["win_rate"] * 100, 1),
            "total_profit": round(stats["total_winnings"] - stats["total_wagered"], 2),
            "roi": round(stats["roi"] * 100, 1),
            "total_wagered": round(stats["total_wagered"], 2),
            "total_winnings": round(stats["total_winnings"], 2),
            "favorite_sport": stats["favorite_sport"],
            "favorite_bet_type": stats["favorite_bet_type"],
            "win_streak": stats.get("current_streak", {}).get("count", 0),
            "weekly_bet_change": weekly_bet_change,
            "accuracy_change": accuracy_change,
            "profit_change": profit_change,
            "trend_direction": trends.get("trend_direction", "stable"),
        }

        # Return in the format expected by frontend
        return {
            "status": "success",
            "personal_stats": personal_stats,
            "metrics": {
                "total_predictions": stats["total_bets"],
                "overall_accuracy": round(stats["win_rate"] * 100, 1),
                "total_wagered": round(stats["total_wagered"], 2),
                "net_profit": round(
                    stats["total_winnings"] - stats["total_wagered"], 2
                ),
                "resolved_predictions": stats.get(
                    "total_resolved_bets", stats["total_bets"]
                ),
                "pending_predictions": stats.get("total_pending_bets", 0),
                "success_rate": stats["win_rate"],
                "by_sport": stats.get("by_sport", {}),
                "by_type": stats.get("by_bet_type", {}),
                "trends": {
                    "last_7_days_accuracy": round(
                        stats.get("last_7_days_accuracy", stats["win_rate"]) * 100,
                        1,
                    ),
                    "improvement_trend": trends.get("trend_direction", "stable"),
                    "weekly_bet_change": weekly_bet_change,
                    "accuracy_change": accuracy_change,
                    "profit_change": profit_change,
                },
                "period_days": 30,
            },
            "user_id": user_id,
        }
    except Exception as e:
        logger.error(f"Error fetching user performance: {e}")

        # Return fallback data with zeros instead of fake data
        user_id = current_user.get("id") or current_user.get("user_id")
        return {
            "status": "success",
            "personal_stats": {
                "predictions_made": 0,
                "accuracy_rate": 0,
                "total_profit": 0,
                "roi": 0,
                "total_wagered": 0,
                "total_winnings": 0,
                "favorite_sport": "N/A",
                "favorite_bet_type": "N/A",
                "win_streak": 0,
                "weekly_bet_change": 0,
                "accuracy_change": 0,
                "profit_change": 0,
                "trend_direction": "stable",
            },
            "metrics": {
                "total_predictions": 0,
                "overall_accuracy": 0,
                "total_wagered": 0,
                "net_profit": 0,
                "resolved_predictions": 0,
                "pending_predictions": 0,
                "success_rate": 0,
                "by_sport": {},
                "by_type": {},
                "trends": {
                    "last_7_days_accuracy": 0,
                    "improvement_trend": "stable",
                    "weekly_bet_change": 0,
                    "accuracy_change": 0,
                    "profit_change": 0,
                },
                "period_days": 30,
            },
            "user_id": user_id,
        }


@app.options("/api/leaderboard")
async def options_leaderboard():
    """Handle CORS preflight for leaderboard endpoint"""
    return {}


@app.get("/api/leaderboard")
async def get_leaderboard(
    period: str = "weekly", current_user: dict = Depends(get_current_user)
):
    """Get leaderboard with real user betting statistics"""
    try:
        # Get all users from database
        from app.core.database import SessionLocal
        from app.models.database_models import User

        db = SessionLocal()
        try:
            # Get all users excluding hidden ones
            users = db.query(User).filter(User.is_hidden == False).all()
            leaderboard_data = []

            # Calculate days for period (not currently used for filtering)
            days = {"weekly": 7, "monthly": 30, "all_time": 365}.get(period, 7)

            for user in users:
                try:
                    # Get user bet stats from unified service
                    stats = await simple_unified_bet_service.get_user_stats(user.id)

                    # Calculate metrics (default to 0 for users with no bets)
                    total_wagered = stats.get("total_wagered", 0) if stats else 0
                    profit_loss = stats.get("profit_loss", 0) if stats else 0
                    win_rate = stats.get("win_rate", 0) if stats else 0
                    total_bets = stats.get("total_bets", 0) if stats else 0

                    # Include ALL users, even those with no bets
                    roi = (
                        (profit_loss / total_wagered * 100) if total_wagered > 0 else 0
                    )

                    leaderboard_data.append(
                        {
                            "user_id": user.id,
                            "username": user.username or f"User{user.id}",
                            "profit": profit_loss,
                            "win_rate": win_rate,
                            "roi": roi,
                            "total_bets": total_bets,
                            "total_wagered": total_wagered,
                        }
                    )
                except Exception as e:
                    logger.error(f"Error calculating stats for user {user.id}: {e}")
                    continue

            # Sort by profit (descending)
            leaderboard_data.sort(key=lambda x: x["profit"], reverse=True)

            # Add rank and format data
            ranked_leaderboard = []
            for i, user_data in enumerate(leaderboard_data):
                ranked_leaderboard.append(
                    {
                        "rank": i + 1,
                        "user_id": user_data["user_id"],
                        "username": user_data["username"],
                        "profit": round(user_data["profit"]),
                        "win_rate": round(user_data["win_rate"]),
                        "roi": round(user_data["roi"]),
                        "total_bets": user_data["total_bets"],
                        "total_wagered": round(user_data["total_wagered"]),
                        "is_current_user": user_data["user_id"]
                        == (current_user.get("id") or current_user.get("user_id")),
                    }
                )

            # Get current user's position
            current_user_rank = None
            for entry in ranked_leaderboard:
                if entry["is_current_user"]:
                    current_user_rank = entry["rank"]
                    break

            # Stats for the summary section
            total_players = len(users)
            active_players = len(leaderboard_data)

            # Get current user's profit
            current_user_profit = 0
            if current_user_rank and current_user_rank <= len(leaderboard_data):
                current_user_profit = leaderboard_data[current_user_rank - 1]["profit"]

            return {
                "status": "success",
                "period": period,
                "leaderboard": ranked_leaderboard[:50],  # Top 50
                "current_user_rank": current_user_rank,
                "stats": {
                    "total_players": total_players,
                    "active_players": active_players,
                    "current_user_points": current_user_profit,
                },
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch leaderboard")


# Simple endpoints for bets and odds that frontend might expect
@app.options("/api/bets")
async def options_simple_bets():
    """Handle CORS preflight for simple bets endpoint"""
    return {}


@app.get("/api/bets")
async def get_simple_bets(current_user: dict = Depends(get_current_user)):
    """Get user's bets - simplified endpoint"""
    try:
        bets = await simple_unified_bet_service.get_user_bets(
            current_user.get("id") or current_user.get("user_id"),
            include_legs=False,  # Don't include parlay legs by default
        )
        return {"status": "success", "bets": bets}
    except Exception as e:
        logger.error(f"Error fetching user bets: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user bets")


@app.options("/api/odds")
async def options_simple_odds():
    """Handle CORS preflight for simple odds endpoint"""
    return {}


# ============================================================================
# SUBSCRIPTION ENDPOINTS
# ============================================================================


@app.post("/api/subscription/create-checkout")
async def create_checkout_session(
    request: dict,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create Stripe Checkout session for subscription upgrade"""
    try:
        from app.services.subscription_service import SubscriptionService
        from app.models.database_models import User

        tier = request.get("tier")
        return_url = request.get("return_url", f"{settings.FRONTEND_URL}/dashboard")

        if not tier:
            raise HTTPException(status_code=400, detail="Subscription tier is required")

        # Get user from database
        user_id = current_user.get("id") or current_user.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create checkout session
        subscription_service = SubscriptionService(db)
        result = subscription_service.create_checkout_session(user, tier, return_url)

        return {
            "status": "success",
            "client_secret": result["client_secret"],
            "session_id": result["session_id"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Checkout creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/subscription/session-status/{session_id}")
async def get_session_status(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get checkout session status and update user subscription if completed"""
    try:
        from app.services.subscription_service import SubscriptionService
        from app.models.database_models import User

        user_id = current_user.get("id") or current_user.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        subscription_service = SubscriptionService(db)
        status = subscription_service.get_session_status(session_id, user)

        return status

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/subscription/webhook")
async def stripe_webhook(request: dict):
    """Handle Stripe webhook events"""
    import stripe

    try:
        # Get the webhook secret from environment
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            logger.warning("STRIPE_WEBHOOK_SECRET not configured")
            return {"status": "ignored"}

        # Verify webhook signature
        signature = request.headers.get("stripe-signature")
        try:
            event = stripe.Webhook.construct_event(
                await request.body(), signature, webhook_secret
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")

        # Handle the event
        db = SessionLocal()
        try:
            from app.services.subscription_service import SubscriptionService

            subscription_service = SubscriptionService(db)

            if event["type"] == "checkout.session.completed":
                session = event["data"]["object"]
                subscription_service.handle_checkout_completed(session)

            elif event["type"] in [
                "customer.subscription.updated",
                "customer.subscription.deleted",
            ]:
                subscription = event["data"]["object"]
                subscription_service.handle_subscription_updated(subscription)

            logger.info(f"Processed webhook event: {event['type']}")
            return {"status": "success"}

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


@app.get("/api/subscription/info")
async def get_subscription_info(
    current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get current subscription information"""
    try:
        from app.services.subscription_service import SubscriptionService
        from app.models.database_models import User

        user_id = current_user.get("id") or current_user.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        subscription_service = SubscriptionService(db)
        subscription_info = subscription_service.get_subscription_info(user)

        return {
            "status": "success",
            "subscription": subscription_info
            or {"tier": user.subscription_tier, "status": "free"},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get subscription info error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get subscription info")


@app.post("/api/subscription/cancel")
async def cancel_subscription(
    current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Cancel current subscription"""
    try:
        from app.services.subscription_service import SubscriptionService
        from app.models.database_models import User

        user_id = current_user.get("id") or current_user.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        subscription_service = SubscriptionService(db)
        result = subscription_service.cancel_subscription(user)

        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "Cancellation failed")
            )

        return {
            "status": "success",
            "message": result["message"],
            "period_end": result.get("period_end"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cancel subscription error: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")


@app.get("/api/odds")
async def get_simple_odds():
    """Get current odds - simplified endpoint"""
    # Redirect to popular odds endpoint
    return await get_popular_sports_odds()


# Predictions endpoints
@app.options("/api/predictions/personalized")
async def options_personalized_predictions():
    """Handle CORS preflight for personalized predictions"""
    return {}


@app.get("/api/predictions/personalized")
async def get_personalized_predictions(current_user: dict = Depends(get_current_user)):
    """Get personalized predictions for the user"""
    try:
        yetai_service = get_service("yetai_bets_service")
        user_tier = current_user.get("subscription_tier", "free")

        # Get user's bets based on their tier
        bets = await yetai_service.get_active_bets(user_tier)

        # Transform bets into predictions format
        predictions = []
        for bet in bets:
            prediction = {
                "id": bet.get("id"),
                "title": bet.get("game"),  # YetAI service uses 'game' not 'title'
                "description": bet.get(
                    "reasoning"
                ),  # YetAI service uses 'reasoning' not 'description'
                "sport": bet.get("sport", "NFL"),
                "confidence": bet.get("confidence", 75),
                "bet_type": bet.get("bet_type"),
                "selection": bet.get(
                    "pick"
                ),  # YetAI service uses 'pick' not 'selection'
                "odds": bet.get("odds"),
                "game_date": bet.get("game_time"),  # YetAI service uses 'game_time'
                "reason": bet.get(
                    "reasoning",
                    f"AI analysis with {bet.get('confidence', 75)}% confidence based on historical data",
                ),
            }
            predictions.append(prediction)

        return {"status": "success", "predictions": predictions, "user_tier": user_tier}

    except Exception as e:
        logger.error(f"Error fetching personalized predictions: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch personalized predictions"
        )


# Avatar endpoints
@app.options("/api/user/avatar")
async def options_user_avatar():
    """Handle CORS preflight for user avatar"""
    return {}


@app.get("/api/user/avatar")
async def get_user_avatar(current_user: dict = Depends(get_current_user)):
    """Get user avatar URL"""
    try:
        auth_service = get_service("auth_service")
        user_data = await auth_service.get_user_profile(
            current_user.get("id") or current_user.get("user_id")
        )
        avatar_url = user_data.get("avatar_url")

        if avatar_url:
            return {"status": "success", "avatar_url": avatar_url}
        else:
            # Generate default avatar URL using avatar service
            from app.services.avatar_service import avatar_service

            default_avatar = avatar_service.get_avatar_url(user_data)
            return {"status": "success", "avatar_url": default_avatar}

    except Exception as e:
        logger.error(f"Error fetching user avatar: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user avatar")


@app.post("/api/user/avatar")
async def upload_user_avatar(current_user: dict = Depends(get_current_user)):
    """Upload user avatar"""
    if is_service_available("auth_service"):
        try:
            # In a real implementation, handle file upload here
            user_id = current_user.get("id") or current_user.get("user_id")
            return {
                "status": "success",
                "message": "Avatar upload endpoint ready",
                "user_id": user_id,
            }
        except Exception as e:
            logger.error(f"Error uploading avatar: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload avatar")

    return {"status": "error", "message": "Avatar upload service unavailable"}


@app.post("/api/auth/avatar")
async def upload_auth_avatar(
    avatar_data: dict, current_user: dict = Depends(get_current_user)
):
    """Upload user avatar via auth endpoint"""
    try:
        if not is_service_available("auth_service"):
            raise HTTPException(status_code=503, detail="Auth service unavailable")

        auth_service = get_service("auth_service")
        user = await auth_service.get_user_by_id(
            current_user.get("id") or current_user.get("user_id")
        )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        image_data = avatar_data.get("image_data")
        if not image_data:
            raise HTTPException(status_code=400, detail="No image data provided")

        # Delete old avatar if exists
        if user.get("avatar_url"):
            from app.services.avatar_service import avatar_service

            avatar_service.delete_avatar(
                user["avatar_url"], user.get("avatar_thumbnail")
            )

        # Save new avatar
        from app.services.avatar_service import avatar_service

        success, result = avatar_service.save_avatar(
            current_user.get("id") or current_user.get("user_id"), image_data
        )

        if success:
            # Convert relative URLs to full URLs for local storage
            avatar_url = result["avatar"]
            thumbnail_url = result["thumbnail"]

            # If using local storage (relative paths), convert to full URLs
            if not avatar_url.startswith("http"):
                from app.core.config import settings

                if settings.ENVIRONMENT == "production":
                    base_url = "https://api.yetai.app"
                elif settings.ENVIRONMENT == "staging":
                    base_url = "https://staging-api.yetai.app"
                else:
                    base_url = "http://localhost:8001"

                avatar_url = f"{base_url}{avatar_url}"
                thumbnail_url = f"{base_url}{thumbnail_url}"

            # Update user record with avatar URLs in database
            update_result = await auth_service.update_user_avatar(
                current_user.get("id") or current_user.get("user_id"),
                result["avatar"],  # Store relative path in DB
                result["thumbnail"],
            )

            if update_result.get("success"):
                return {
                    "status": "success",
                    "message": "Avatar uploaded successfully",
                    "avatar_url": avatar_url,  # Return full URL
                    "thumbnail_url": thumbnail_url,
                }
            else:
                raise HTTPException(
                    status_code=500, detail="Failed to update user avatar"
                )
        else:
            # Improved error messages for users
            error_msg = result if isinstance(result, str) else "Invalid image file"
            raise HTTPException(status_code=400, detail=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading avatar: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to upload avatar: {str(e)}"
        )


@app.delete("/api/auth/avatar")
async def delete_auth_avatar(current_user: dict = Depends(get_current_user)):
    """Delete user avatar via auth endpoint"""
    try:
        if not is_service_available("auth_service"):
            raise HTTPException(status_code=503, detail="Auth service unavailable")

        auth_service = get_service("auth_service")
        user = await auth_service.get_user_by_id(
            current_user.get("id") or current_user.get("user_id")
        )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete avatar files
        if user.get("avatar_url"):
            from app.services.avatar_service import avatar_service

            avatar_service.delete_avatar(
                user["avatar_url"], user.get("avatar_thumbnail")
            )

            # Clear avatar URLs from database
            update_result = await auth_service.update_user_avatar(
                current_user.get("id") or current_user.get("user_id"), None, None
            )

            if update_result.get("success"):
                return {"status": "success", "message": "Avatar deleted successfully"}
            else:
                raise HTTPException(
                    status_code=500, detail="Failed to update user avatar"
                )
        else:
            raise HTTPException(status_code=400, detail="No avatar to delete")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting avatar: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete avatar: {str(e)}"
        )


# Sports list endpoint
@app.options("/api/sports")
async def options_sports_list():
    """Handle CORS preflight for sports list"""
    return {}


@app.get("/api/sports")
async def get_sports_list():
    """Get available sports"""
    try:
        sports_service = get_service("sports_pipeline")
        sports = await sports_service.get_available_sports()
        return {"status": "success", "sports": sports}
    except Exception as e:
        logger.error(f"Error fetching sports list: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch sports list")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": f"YetAI Sports Betting MVP - {settings.ENVIRONMENT.title()} API",
        "version": "1.2.0",
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/health",
        "services_available": len(
            [s for s in service_loader.get_status().values() if s]
        ),
        "total_services": len(service_loader.get_status()),
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.put("/api/auth/profile")
async def update_profile(
    profile_data: dict, current_user: dict = Depends(get_current_user)
):
    """Update user profile including email and password"""
    try:
        if not is_service_available("auth_service"):
            raise HTTPException(status_code=503, detail="Auth service unavailable")

        auth_service = get_service("auth_service")

        # If changing password, verify current password first
        if "current_password" in profile_data and "new_password" in profile_data:
            user = await auth_service.get_user_by_id(
                current_user.get("id") or current_user.get("user_id")
            )
            if not user or not auth_service.verify_password(
                profile_data["current_password"], user["password_hash"]
            ):
                raise HTTPException(
                    status_code=400, detail="Current password is incorrect"
                )

            # Update password
            profile_data["password"] = profile_data["new_password"]
            del profile_data["current_password"]
            del profile_data["new_password"]

        # Update user
        updated_user = await auth_service.update_user(
            current_user.get("id") or current_user.get("user_id"), profile_data
        )

        if updated_user:
            return {
                "status": "success",
                "message": "Profile updated successfully",
                "user": updated_user,
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to update profile")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating profile: {str(e)}")


# Authentication API endpoints
@app.get("/api/auth/status")
async def auth_status():
    """Check authentication status"""
    return {
        "authenticated": False,
        "auth_available": is_service_available("auth_service"),
        "message": (
            "Authentication service ready"
            if is_service_available("auth_service")
            else "Authentication service unavailable"
        ),
    }


@app.post("/api/auth/register")
async def register(user_data: UserSignup):
    """Register a new user"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, detail="Authentication service is currently unavailable"
        )

    try:
        auth_service = get_service("auth_service")
        result = await auth_service.create_user(
            email=user_data.email,
            password=user_data.password,
            username=user_data.username,
            first_name=user_data.first_name or "",
            last_name=user_data.last_name or "",
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "Registration failed")
            )

        return {
            "status": "success",
            "message": "User registered successfully",
            "user": result.get("user"),
            "access_token": result.get("access_token"),
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
            status_code=503, detail="Authentication service is currently unavailable"
        )

    try:
        auth_service = get_service("auth_service")
        result = await auth_service.authenticate_user(
            email_or_username=credentials.get("email_or_username"),
            password=credentials.get("password"),
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=401, detail=result.get("error", "Invalid credentials")
            )

        return {
            "status": "success",
            "message": "Login successful",
            "access_token": result.get("access_token"),
            "user": result.get("user"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/auth/logout")
async def logout():
    """Logout user"""
    return {"status": "success", "message": "Logged out successfully"}


@app.post("/api/auth/verify-email")
async def verify_email(request: dict):
    """Verify user email with token from verification link"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, detail="Authentication service is currently unavailable"
        )

    try:
        token = request.get("token")
        if not token:
            raise HTTPException(
                status_code=400, detail="Verification token is required"
            )

        auth_service = get_service("auth_service")
        result = await auth_service.verify_email(token)

        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "Email verification failed")
            )

        return {
            "status": "success",
            "message": result.get("message", "Email verified successfully"),
            "user": result.get("user"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email verification error: {e}")
        raise HTTPException(status_code=400, detail="Email verification failed")


@app.post("/api/auth/resend-verification")
async def resend_verification(request: dict):
    """Resend verification email to user"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, detail="Authentication service is currently unavailable"
        )

    try:
        email = request.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        auth_service = get_service("auth_service")
        result = await auth_service.resend_verification_email(email)

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Failed to resend verification email"),
            )

        return {
            "status": "success",
            "message": result.get("message", "Verification email sent successfully"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resend verification error: {e}")
        raise HTTPException(
            status_code=400, detail="Failed to resend verification email"
        )


@app.post("/api/auth/forgot-password")
async def forgot_password(request: dict):
    """Request password reset email"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, detail="Authentication service is currently unavailable"
        )

    try:
        email = request.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")

        auth_service = get_service("auth_service")
        result = await auth_service.request_password_reset(email)

        # Always return success to prevent email enumeration
        return {
            "status": "success",
            "message": "If the email exists, a password reset link has been sent",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Forgot password error: {e}")
        raise HTTPException(status_code=400, detail="Failed to process request")


@app.post("/api/auth/reset-password")
async def reset_password(request: dict):
    """Reset password with token"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, detail="Authentication service is currently unavailable"
        )

    try:
        token = request.get("token")
        new_password = request.get("new_password")

        if not token or not new_password:
            raise HTTPException(
                status_code=400, detail="Token and new password are required"
            )

        auth_service = get_service("auth_service")
        result = await auth_service.reset_password(token, new_password)

        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error", "Password reset failed")
            )

        return {
            "status": "success",
            "message": result.get("message", "Password reset successfully"),
            "user": result.get("user"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        raise HTTPException(status_code=400, detail="Failed to reset password")


# Google OAuth endpoints
@app.get("/api/auth/google/url")
async def get_google_auth_url():
    """Get Google OAuth authorization URL"""
    if not GOOGLE_OAUTH_AVAILABLE or google_oauth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not available. Please contact support.",
        )

    try:
        result = google_oauth_service.get_authorization_url()
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return {
            "status": "success",
            "authorization_url": result["authorization_url"],
            "state": result["state"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google auth URL error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get authorization URL: {str(e)}"
        )


@app.get("/api/auth/google/callback")
async def google_oauth_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Handle Google OAuth callback"""
    if not GOOGLE_OAUTH_AVAILABLE or google_oauth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not available. Please contact support.",
        )

    try:
        from app.services.auth_service_db import auth_service_db

        result = google_oauth_service.handle_callback(code, state)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        user_info = result["user_info"]

        # Check if user already exists
        existing_user = await auth_service_db.get_user_by_email(user_info["email"])

        if existing_user:
            # User exists - log them in
            access_token = auth_service_db.generate_token(existing_user["id"])
            user_data = existing_user
        else:
            # Create new user with Google OAuth
            # Generate unique username from email - sanitize to only allow valid characters
            import re
            import secrets as sec

            base_username = user_info["email"].split("@")[0]
            # Remove invalid characters (only allow letters, numbers, underscores, hyphens)
            username = re.sub(r"[^a-zA-Z0-9_-]", "", base_username)

            # If username is empty after sanitization, generate one
            if not username:
                username = f"user_{sec.token_hex(4)}"

            # Since OAuth users don't have passwords, we'll generate a random one
            random_password = sec.token_urlsafe(32)

            result = await auth_service_db.create_user(
                email=user_info["email"],
                password=random_password,
                username=username,
                first_name=user_info.get("first_name", ""),
                last_name=user_info.get("last_name", ""),
            )

            if not result["success"]:
                raise HTTPException(status_code=400, detail=result["error"])

            # Generate access token
            access_token = auth_service_db.generate_token(result["user"]["id"])
            user_data = result["user"]

        # Redirect to frontend with token and user data encoded in URL
        from fastapi.responses import RedirectResponse
        import json
        import urllib.parse

        frontend_url = settings.get_frontend_urls()[0]  # Get primary frontend URL
        # Encode user data as base64 to pass in URL safely
        import base64

        user_json = json.dumps(user_data)
        user_encoded = base64.b64encode(user_json.encode()).decode()

        redirect_url = f"{frontend_url}/auth/callback?token={access_token}&user={urllib.parse.quote(user_encoded)}"
        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {str(e)}")


@app.post("/api/auth/google/verify")
async def verify_google_token(data: dict, db: Session = Depends(get_db)):
    """Verify Google ID token (for client-side OAuth)"""
    if not GOOGLE_OAUTH_AVAILABLE or google_oauth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not available. Please contact support.",
        )

    try:
        from app.services.auth_service_db import auth_service_db

        id_token = data.get("id_token")
        if not id_token:
            raise HTTPException(status_code=400, detail="ID token is required")

        user_info = google_oauth_service.verify_id_token(id_token)
        if not user_info:
            raise HTTPException(status_code=400, detail="Invalid ID token")

        # Check if user already exists
        existing_user = await auth_service_db.get_user_by_email(user_info["email"])

        if existing_user:
            # User exists - log them in
            access_token = auth_service_db.generate_token(existing_user["id"])

            return {
                "status": "success",
                "message": "Login successful",
                "access_token": access_token,
                "token_type": "bearer",
                "user": existing_user,
            }
        else:
            # Create new user with Google OAuth
            # Generate unique username from email - sanitize to only allow valid characters
            import re
            import secrets as sec

            base_username = user_info["email"].split("@")[0]
            # Remove invalid characters (only allow letters, numbers, underscores, hyphens)
            username = re.sub(r"[^a-zA-Z0-9_-]", "", base_username)

            # If username is empty after sanitization, generate one
            if not username:
                username = f"user_{sec.token_hex(4)}"

            # Since OAuth users don't have passwords, we'll generate a random one
            random_password = sec.token_urlsafe(32)

            result = await auth_service_db.create_user(
                email=user_info["email"],
                password=random_password,
                username=username,
                first_name=user_info.get("first_name", ""),
                last_name=user_info.get("last_name", ""),
            )

            if not result["success"]:
                raise HTTPException(status_code=400, detail=result["error"])

            # Generate access token
            access_token = auth_service_db.generate_token(result["user"]["id"])

            return {
                "status": "success",
                "message": "Account created successfully",
                "access_token": access_token,
                "token_type": "bearer",
                "user": result["user"],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google token verification error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Token verification failed: {str(e)}"
        )


@app.get("/api/auth/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user info"""
    if not is_service_available("auth_service"):
        raise HTTPException(
            status_code=503, detail="Authentication service is currently unavailable"
        )

    # Get auth service to fetch full user data
    auth_service = get_service("auth_service")
    try:
        # Get full user data from database using user_id
        user_data = await auth_service.get_user_by_id(
            current_user.get("id") or current_user.get("user_id")
        )
        if user_data:
            return {"status": "success", "user": user_data}
        else:
            # Fallback to basic user info from token
            return {"status": "success", "user": current_user}
    except Exception as e:
        logger.error(f"Error fetching user data: {e}")
        # Fallback to basic user info from token
        return {"status": "success", "user": current_user}


@app.get("/api/auth/avatar/{user_id}")
async def get_auth_user_avatar(user_id: int):
    """Get user avatar by user ID for auth purposes"""
    try:
        if is_service_available("auth_service"):
            auth_service = get_service("auth_service")
            user_data = await auth_service.get_user_by_id(user_id)

            if not user_data:
                raise HTTPException(status_code=404, detail="User not found")

            # Use avatar service to get avatar URL
            from app.services.avatar_service import avatar_service

            avatar_url = avatar_service.get_avatar_url(user_data)
            return {"status": "success", "avatar_url": avatar_url}
        else:
            # Return default avatar when service unavailable
            from app.services.avatar_service import avatar_service

            default_avatar = avatar_service.generate_default_avatar(
                f"user{user_id}@example.com", f"User {user_id}"
            )
            return {"status": "success", "avatar_url": default_avatar}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching auth user avatar: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user avatar")


@app.get("/api/auth/2fa/status")
async def get_2fa_status(current_user: dict = Depends(get_current_user)):
    """Get 2FA status for current user"""
    try:
        if is_service_available("auth_service"):
            auth_service = get_service("auth_service")
            result = await auth_service.get_2fa_status(
                current_user.get("id") or current_user.get("user_id")
            )

            if result["success"]:
                return {
                    "status": "success",
                    "enabled": result["enabled"],
                    "backup_codes_remaining": result["backup_codes_remaining"],
                    "setup_in_progress": result["setup_in_progress"],
                }
            else:
                raise HTTPException(status_code=400, detail=result["error"])
        else:
            # Return default 2FA status when service unavailable
            return {
                "status": "success",
                "enabled": False,
                "backup_codes_remaining": 0,
                "setup_in_progress": False,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching 2FA status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get 2FA status: {str(e)}"
        )


@app.put("/api/auth/preferences")
async def update_preferences(
    preferences: UserPreferences, current_user: dict = Depends(get_current_user)
):
    """Update user preferences"""
    try:
        if not is_service_available("auth_service"):
            raise HTTPException(status_code=503, detail="Auth service unavailable")

        auth_service = get_service("auth_service")
        result = await auth_service.update_user_preferences(
            current_user.get("id") or current_user.get("user_id"),
            preferences=preferences.dict(exclude_unset=True),
        )

        if result["success"]:
            return {"status": "success", "message": "Preferences updated successfully"}
        else:
            raise HTTPException(status_code=400, detail=result["error"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating preferences: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update preferences: {str(e)}"
        )


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
            bets = await yetai_service.get_active_bets(user_tier)

            return {
                "status": "success",
                "bets": bets,
                "user_tier": user_tier,
                "message": f"YetAI bets for {user_tier} tier user",
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
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ]

    # Pro users get more bets
    if user_tier == "pro":
        mock_bets.append(
            {
                "id": "mock_yetai_2",
                "title": "Lakers Spread Value",
                "description": "Advanced analytics show Lakers covering the spread at 85% confidence",
                "bet_type": "spread",
                "selection": "Los Angeles Lakers -3.5",
                "odds": -110,
                "confidence": 0.85,
                "tier_requirement": "pro",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    return {
        "status": "success",
        "bets": mock_bets,
        "user_tier": user_tier,
        "message": f"Mock YetAI bets for {user_tier} tier user - service unavailable",
    }


@app.options("/api/admin/yetai-bets/{bet_id}")
async def options_admin_delete_yetai_bet():
    """Handle CORS preflight for admin YetAI bet deletion"""
    return {}


@app.delete("/api/admin/yetai-bets/{bet_id}")
async def delete_yetai_bet(bet_id: str, admin_user: dict = Depends(require_admin)):
    """Delete YetAI bet (Admin only)"""

    if is_service_available("yetai_bets_service"):
        try:
            yetai_service = get_service("yetai_bets_service")
            result = await yetai_service.delete_bet(bet_id, admin_user["id"])

            return {
                "status": "success",
                "message": f"YetAI bet {bet_id} deleted successfully",
                "result": result,
            }
        except Exception as e:
            logger.error(f"Error deleting YetAI bet {bet_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete bet")

    # Mock response when service unavailable
    return {
        "status": "success",
        "message": f"Mock deletion of YetAI bet {bet_id} - service unavailable",
    }


@app.post("/api/admin/yetai-bets")
async def create_yetai_bet(
    bet_request: CreateYetAIBetRequest, admin_user: dict = Depends(require_admin)
):
    """Create a new YetAI Bet (Admin only)"""
    try:
        if is_service_available("yetai_bets_service"):
            yetai_service = get_service("yetai_bets_service")
            result = await yetai_service.create_bet(bet_request, admin_user["id"])

            if result.get("success"):
                return {
                    "status": "success",
                    "message": result.get("message", "Bet created successfully"),
                    "bet_id": result.get("bet_id"),
                }
            else:
                raise HTTPException(
                    status_code=400, detail=result.get("error", "Failed to create bet")
                )
        else:
            # Mock response when service unavailable
            import uuid

            mock_bet_id = str(uuid.uuid4())
            return {
                "status": "success",
                "message": "Mock YetAI bet created successfully - service unavailable",
                "bet_id": mock_bet_id,
                "bet_data": bet_request.dict(),
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating YetAI bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to create bet")


@app.post("/api/admin/yetai-parlays")
async def create_yetai_parlay(
    parlay_request: CreateParlayBetRequest, admin_user: dict = Depends(require_admin)
):
    """Create a new YetAI Parlay Bet (Admin only)"""
    try:
        if is_service_available("yetai_bets_service"):
            yetai_service = get_service("yetai_bets_service")
            result = await yetai_service.create_parlay_bet(
                parlay_request, admin_user["id"]
            )

            if result.get("success"):
                return {
                    "status": "success",
                    "message": result.get("message", "Parlay created successfully"),
                    "parlay_id": result.get("bet_id"),
                }
            else:
                raise HTTPException(
                    status_code=400,
                    detail=result.get("error", "Failed to create parlay"),
                )
        else:
            # Mock response when service unavailable
            import uuid

            mock_parlay_id = str(uuid.uuid4())
            return {
                "status": "success",
                "message": "Mock YetAI parlay created successfully - service unavailable",
                "parlay_id": mock_parlay_id,
                "parlay_data": parlay_request.dict(),
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating YetAI parlay: {e}")
        raise HTTPException(status_code=500, detail="Failed to create parlay")


@app.post("/api/admin/sync-games")
async def sync_games(admin_user: dict = Depends(require_admin)):
    """Sync today's games from Odds API and ESPN (Admin only)"""
    try:
        import sys
        import subprocess  # nosec B404 - subprocess used safely with hardcoded paths
        from pathlib import Path

        script_path = Path(__file__).parent.parent / "scripts" / "fetch_todays_games.py"

        logger.info(f"Admin {admin_user['id']} triggered game sync")

        # Run the sync script with hardcoded script path (no user input)
        result = subprocess.run(  # nosec B603 - using sys.executable and hardcoded script path
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            # Parse output for summary
            output_lines = result.stdout.split("\n")
            summary = {
                "status": "success",
                "message": "Games synced successfully",
                "details": [
                    line
                    for line in output_lines
                    if "Total" in line or "Sync Results" in line or "✅" in line
                ],
            }
            logger.info(f"Game sync completed successfully")
            return summary
        else:
            logger.error(f"Game sync failed: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"Sync failed: {result.stderr[:200]}",
            )

    except subprocess.TimeoutExpired:
        logger.error("Game sync timed out after 120 seconds")
        raise HTTPException(status_code=500, detail="Sync timed out")
    except Exception as e:
        logger.error(f"Error syncing games: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync games: {str(e)}")


@app.options("/api/admin/users")
async def options_admin_get_users():
    """Handle CORS preflight for admin get users"""
    return {}


@app.get("/api/admin/users")
async def get_admin_users(admin_user: dict = Depends(require_admin)):
    """Get all users (Admin only)"""
    try:
        if is_service_available("auth_service"):
            from app.services.auth_service_db import auth_service_db

            users = await auth_service_db.get_all_users()

            return {"status": "success", "users": users}
        else:
            # Mock response when service unavailable
            mock_users = [
                {
                    "id": 1,
                    "email": "admin@example.com",
                    "first_name": "Admin",
                    "last_name": "User",
                    "is_admin": True,
                    "created_at": "2024-01-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "email": "user@example.com",
                    "first_name": "Regular",
                    "last_name": "User",
                    "is_admin": False,
                    "created_at": "2024-01-02T00:00:00Z",
                },
            ]
            return {
                "status": "success",
                "users": mock_users,
                "message": "Mock users - service unavailable",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch users")


@app.options("/api/admin/users/{user_id}")
async def options_admin_update_user():
    """Handle CORS preflight for admin update user"""
    return {}


@app.put("/api/admin/users/{user_id}")
async def update_admin_user(
    user_id: int, update_data: dict, admin_user: dict = Depends(require_admin)
):
    """Update user information (Admin only)"""
    try:
        if is_service_available("auth_service"):
            from app.services.auth_service_db import auth_service_db

            updated_user = await auth_service_db.update_user(user_id, update_data)

            if updated_user:
                return {
                    "status": "success",
                    "user": updated_user,
                    "message": f"User {user_id} updated successfully",
                }
            else:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        else:
            # Mock response when service unavailable
            return {
                "status": "success",
                "user": {
                    "id": user_id,
                    **update_data,
                    "updated_at": "2024-01-01T00:00:00Z",
                },
                "message": f"Mock update of user {user_id} - service unavailable",
            }

    except ValueError as e:
        # Validation errors from the service
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user")


@app.post("/api/admin/users")
async def create_admin_user(user_data: dict, admin_user: dict = Depends(require_admin)):
    """Create a new user (Admin only)"""
    try:
        if is_service_available("auth_service"):
            from app.services.auth_service_db import auth_service_db

            # Extract required fields
            email = user_data.get("email")
            password = user_data.get("password")
            username = user_data.get("username")
            first_name = user_data.get("first_name")
            last_name = user_data.get("last_name")
            subscription_tier = user_data.get("subscription_tier", "free")
            is_admin = user_data.get("is_admin", False)
            is_verified = user_data.get("is_verified", False)

            if not email or not password or not username:
                raise HTTPException(
                    status_code=400, detail="Email, password, and username are required"
                )

            result = await auth_service_db.create_user(
                email=email,
                password=password,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )

            if result.get("success"):
                # Update additional fields if provided
                user_id = result.get("user_id")
                if user_id and (subscription_tier != "free" or is_admin or is_verified):
                    update_data = {}
                    if subscription_tier != "free":
                        update_data["subscription_tier"] = subscription_tier
                    if is_admin:
                        update_data["is_admin"] = is_admin
                    if is_verified:
                        update_data["is_verified"] = is_verified

                    if update_data:
                        await auth_service_db.update_user(user_id, update_data)

                return {
                    "status": "success",
                    "message": "User created successfully",
                    "user_id": result.get("user_id"),
                }
            else:
                raise HTTPException(
                    status_code=400, detail=result.get("error", "Failed to create user")
                )
        else:
            # Mock response when service unavailable
            return {
                "status": "success",
                "message": "Mock user creation - service unavailable",
                "user_id": 999,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")


@app.options("/api/admin/users/{user_id}/reset-password")
async def options_admin_reset_password():
    """Handle CORS preflight for admin reset password"""
    return {}


@app.post("/api/admin/users/{user_id}/reset-password")
async def reset_user_password(user_id: int, admin_user: dict = Depends(require_admin)):
    """Reset user password (Admin only)"""
    try:
        if is_service_available("auth_service"):
            from app.services.auth_service_db import auth_service_db
            import secrets
            import string

            # Generate a new temporary password
            temp_password = "".join(
                secrets.choice(string.ascii_letters + string.digits) for _ in range(12)
            )

            # Update the user's password
            hashed_password = auth_service_db.hash_password(temp_password)
            update_data = {"password_hash": hashed_password}

            # We need to directly update the password_hash field since update_user doesn't handle passwords
            # For now, let's create a simple implementation
            from app.core.database import SessionLocal
            from app.models.database_models import User

            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise HTTPException(
                        status_code=404, detail=f"User {user_id} not found"
                    )

                user.password_hash = hashed_password
                db.commit()

                return {
                    "status": "success",
                    "message": f"Password reset for user {user_id}",
                    "temporary_password": temp_password,
                    "note": "User should change this password on next login",
                }
            finally:
                db.close()
        else:
            # Mock response when service unavailable
            return {
                "status": "success",
                "message": f"Mock password reset for user {user_id} - service unavailable",
                "temporary_password": "temp123456",
                "note": "This is a mock response",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting password for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset password")


@app.options("/api/admin/users/{user_id}")
async def options_admin_delete_user():
    """Handle CORS preflight for admin delete user"""
    return {}


@app.delete("/api/admin/users/{user_id}")
async def delete_admin_user(user_id: int, admin_user: dict = Depends(require_admin)):
    """Delete a user (Admin only)"""
    try:
        # Prevent admin from deleting themselves
        if user_id == admin_user.get("id"):
            raise HTTPException(
                status_code=400, detail="Cannot delete your own account"
            )

        if is_service_available("auth_service"):
            from app.services.auth_service_db import auth_service_db

            # Delete the user
            success = await auth_service_db.delete_user(user_id)

            if success:
                return {
                    "status": "success",
                    "message": f"User {user_id} deleted successfully",
                }
            else:
                raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        else:
            # Mock response when service unavailable
            return {
                "status": "success",
                "message": f"Mock delete of user {user_id} - service unavailable",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user")


@app.options("/api/admin/users/{user_id}/bets")
async def options_admin_delete_user_bets():
    """Handle CORS preflight for admin delete user bets"""
    return {}


@app.delete("/api/admin/users/{user_id}/bets")
async def delete_user_bets(user_id: int, admin_user: dict = Depends(require_admin)):
    """Delete all user bets (Admin only)"""
    try:
        if is_service_available("bet_service"):
            # Since there's no specific method to delete all user bets, we'll implement a basic version
            from app.core.database import SessionLocal
            from app.models.database_models import User, Bet, ParlayBet
            from app.models.simple_unified_bet_model import SimpleUnifiedBet

            db = SessionLocal()
            try:
                # Verify user exists
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise HTTPException(
                        status_code=404, detail=f"User {user_id} not found"
                    )

                # Delete user's bet history first (to avoid foreign key issues)
                from app.models.database_models import BetHistory

                history_deleted = (
                    db.query(BetHistory).filter(BetHistory.user_id == user_id).delete()
                )

                # Delete user's unified bets (new table)
                unified_bets_deleted = (
                    db.query(SimpleUnifiedBet)
                    .filter(SimpleUnifiedBet.user_id == user_id)
                    .delete()
                )

                # Delete user's regular bets (old table)
                bets_deleted = db.query(Bet).filter(Bet.user_id == user_id).delete()

                # Delete user's parlay bets (old table)
                parlay_bets_deleted = (
                    db.query(ParlayBet).filter(ParlayBet.user_id == user_id).delete()
                )

                db.commit()

                total_deleted = (
                    unified_bets_deleted + bets_deleted + parlay_bets_deleted
                )

                return {
                    "status": "success",
                    "message": f"Deleted {total_deleted} bets and {history_deleted} history records for user {user_id}",
                    "bets_deleted": bets_deleted,
                    "parlay_bets_deleted": parlay_bets_deleted,
                    "unified_bets_deleted": unified_bets_deleted,
                    "history_records_deleted": history_deleted,
                }
            finally:
                db.close()
        else:
            # Mock response when service unavailable
            return {
                "status": "success",
                "message": f"Mock deletion of bets for user {user_id} - service unavailable",
                "bets_deleted": 5,
                "parlay_bets_deleted": 2,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting bets for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user bets")


@app.options("/api/admin/cleanup/orphaned-history")
async def options_admin_cleanup_orphaned_history():
    """Handle CORS preflight for admin cleanup orphaned history"""
    return {}


@app.post("/api/admin/cleanup/orphaned-history")
async def cleanup_orphaned_bet_history(admin_user: dict = Depends(require_admin)):
    """Clean up orphaned bet_history records (Admin only)"""
    try:
        from app.core.database import SessionLocal
        from app.models.database_models import BetHistory, Bet, ParlayBet
        from sqlalchemy import text

        db = SessionLocal()
        try:
            # Find bet_history records that don't have corresponding bets
            orphaned_history = db.execute(
                text(
                    """
                SELECT bh.id, bh.bet_id, bh.user_id
                FROM bet_history bh
                LEFT JOIN bets b ON bh.bet_id = b.id
                LEFT JOIN parlay_bets pb ON bh.bet_id = pb.id
                WHERE b.id IS NULL AND pb.id IS NULL
                """
                )
            ).fetchall()

            if not orphaned_history:
                return {
                    "status": "success",
                    "message": "No orphaned bet history records found",
                    "cleaned_up": 0,
                }

            # Delete orphaned records
            orphaned_ids = [str(record.id) for record in orphaned_history]
            deleted_count = (
                db.query(BetHistory)
                .filter(BetHistory.id.in_(orphaned_ids))
                .delete(synchronize_session=False)
            )

            db.commit()

            logger.info(
                f"Admin {admin_user['id']} cleaned up {deleted_count} orphaned bet history records"
            )

            return {
                "status": "success",
                "message": f"Successfully cleaned up {deleted_count} orphaned bet history records",
                "cleaned_up": deleted_count,
                "orphaned_bet_ids": [record.bet_id for record in orphaned_history],
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error cleaning up orphaned bet history: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to cleanup orphaned bet history"
        )


# Admin Bet Verification Endpoints
@app.options("/api/admin/bets/verification/stats")
async def options_verification_stats():
    """Handle CORS preflight for verification stats"""
    return {}


@app.get("/api/admin/bets/verification/stats")
async def get_verification_stats(admin_user: dict = Depends(require_admin)):
    """Get bet verification statistics (Admin only)"""
    try:
        stats = bet_scheduler.get_stats()
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error(f"Error getting verification stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get verification stats")


@app.options("/api/admin/bets/verify")
async def options_verify_bets():
    """Handle CORS preflight for verify bets"""
    return {}


@app.post("/api/admin/bets/debug-verify")
async def debug_bet_verification(
    request: dict, admin_user: dict = Depends(require_admin)
):
    """Debug why a specific bet isn't being verified (Admin only)"""
    try:
        bet_id = request.get("bet_id")
        if not bet_id:
            raise HTTPException(status_code=400, detail="bet_id is required")

        from app.core.database import SessionLocal
        from app.models.simple_unified_bet_model import SimpleUnifiedBet
        from app.services.optimized_odds_api_service import get_optimized_odds_service
        from app.core.config import settings

        db = SessionLocal()
        try:
            # Get the bet
            bet = (
                db.query(SimpleUnifiedBet).filter(SimpleUnifiedBet.id == bet_id).first()
            )
            if not bet:
                return {"status": "error", "message": "Bet not found"}

            logger.info(
                f"🔍 Debug bet {bet_id[:8]}: odds_api_event_id={bet.odds_api_event_id}, "
                f"game_id={bet.game_id}, sport={bet.sport}, status={bet.status}"
            )

            # Get completed games from Odds API
            odds_service = get_optimized_odds_service(settings.ODDS_API_KEY)
            completed_games = await odds_service.get_scores_optimized(
                bet.sport.lower() if bet.sport else "mlb", include_completed=True
            )

            logger.info(f"Found {len(completed_games)} completed games for {bet.sport}")

            # Check if our game is in the list
            game_found = False
            game_data = None
            for game in completed_games:
                if game.get("id") == bet.odds_api_event_id:
                    game_found = True
                    game_data = game
                    logger.info(
                        f"✓ Game found: {game.get('home_team')} vs {game.get('away_team')}"
                    )
                    logger.info(f"  Completed: {game.get('completed')}")
                    logger.info(f"  Scores: {game.get('scores')}")
                    break

            if not game_found:
                logger.warning(
                    f"✗ Game {bet.odds_api_event_id} not found in API results"
                )
                # Log first few games for debugging
                for i, game in enumerate(completed_games[:3]):
                    logger.info(
                        f"  Game {i+1}: ID={game.get('id')} - {game.get('home_team')} vs {game.get('away_team')}"
                    )

            return {
                "status": "success",
                "bet": {
                    "id": bet.id,
                    "odds_api_event_id": bet.odds_api_event_id,
                    "game_id": bet.game_id,
                    "sport": bet.sport,
                    "status": (
                        bet.status.value
                        if hasattr(bet.status, "value")
                        else str(bet.status)
                    ),
                    "selection": bet.selection,
                    "home_team": bet.home_team,
                    "away_team": bet.away_team,
                },
                "api_check": {
                    "game_found": game_found,
                    "total_games": len(completed_games),
                    "game_data": game_data if game_data else None,
                },
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error debugging bet: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/api/admin/bets/verify")
async def run_verification_now(admin_user: dict = Depends(require_admin)):
    """Run bet verification now using unified verification service (Admin only)"""
    try:
        logger.info("🎯 Manual unified verification triggered via API")

        # Simple database test first
        from app.core.database import SessionLocal
        from app.models.simple_unified_bet_model import SimpleUnifiedBet
        from app.models.database_models import BetStatus

        db = SessionLocal()
        try:
            all_bets = db.query(SimpleUnifiedBet).all()
            logger.info(f"DEBUG: Found {len(all_bets)} total bets in unified table")

            pending_count = (
                db.query(SimpleUnifiedBet)
                .filter(SimpleUnifiedBet.status == BetStatus.PENDING)
                .count()
            )
            logger.info(f"DEBUG: Found {pending_count} pending bets")

        except Exception as db_error:
            logger.error(f"Database error: {db_error}", exc_info=True)
            return {
                "status": "error",
                "result": {"error": f"Database error: {str(db_error)}"},
            }
        finally:
            db.close()

        # Use the new unified verification service
        result = await unified_bet_verification_service.verify_all_pending_bets()

        logger.info(f"Unified verification result: {result}")

        # Also sync games to ensure we have latest data
        game_sync_result = {
            "success": True,
            "message": "Game sync skipped for unified verification",
            "games_updated": 0,
            "games_created": 0,
            "sports_synced": [],
        }

        return {
            "status": "success",
            "result": {**result, "game_sync": game_sync_result},
        }
    except Exception as e:
        logger.error(f"Error running unified verification: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to run verification: {str(e)}"
        )


@app.post("/api/admin/bets/sync-status")
async def fix_bet_status_sync(admin_user: dict = Depends(require_admin)):
    """Fix bet status sync between bets and bet_history tables (Admin only)"""
    try:
        logger.info("🔧 Bet status sync fix triggered via admin endpoint")

        from sqlalchemy import text
        from app.models.database_models import Bet, BetStatus, BetHistory, ParlayBet
        from app.core.database import SessionLocal
        from datetime import datetime

        db = SessionLocal()
        try:
            # Find all bets that are PENDING in bets table but have settlement
            # records in bet_history
            query = """
            SELECT DISTINCT
                b.id,
                b.user_id,
                b.parlay_id,
                b.status as current_status,
                bh.new_status as history_status,
                bh.amount as result_amount,
                bh.timestamp as settled_at
            FROM bets b
            JOIN bet_history bh ON b.id = bh.bet_id
            WHERE b.status = 'PENDING'
            AND bh.action = 'settled'
            AND bh.new_status IN ('won', 'lost', 'cancelled')
            ORDER BY bh.timestamp DESC
            """

            result = db.execute(text(query))
            mismatched_bets = result.fetchall()

            # Also check for parlay bets that need syncing
            parlay_query = """
            SELECT DISTINCT
                pb.id,
                pb.user_id,
                NULL as parlay_id,
                pb.status as current_status,
                bh.new_status as history_status,
                bh.amount as result_amount,
                bh.timestamp as settled_at
            FROM parlay_bets pb
            JOIN bet_history bh ON pb.id = bh.bet_id
            WHERE pb.status = 'PENDING'
            AND bh.action = 'settled'
            AND bh.new_status IN ('won', 'lost', 'cancelled')
            ORDER BY bh.timestamp DESC
            """

            parlay_result = db.execute(text(parlay_query))
            mismatched_parlays = parlay_result.fetchall()

            total_mismatched = len(mismatched_bets) + len(mismatched_parlays)

            if total_mismatched == 0:
                logger.info("✅ No bet status mismatches found - all good!")
                return {
                    "success": True,
                    "message": "No bet status mismatches found",
                    "synced_count": 0,
                    "synced_bets": 0,
                    "synced_parlays": 0,
                }

            logger.info(
                f"🔍 Found {len(mismatched_bets)} bet legs and {len(mismatched_parlays)} parlays with status mismatches"
            )

            synced_bets = 0
            synced_parlays = 0
            parlay_ids_to_check = set()

            # Sync individual bet legs
            for bet_row in mismatched_bets:
                bet_id = bet_row[0]
                user_id = bet_row[1]
                parlay_id = bet_row[2]
                current_status = bet_row[3]
                history_status = bet_row[4]
                result_amount = bet_row[5]
                settled_at = bet_row[6]

                logger.info(
                    f"Syncing bet {bet_id[:8]}... (user {user_id}): "
                    f"{current_status} → {history_status}"
                )

                # Update the bet record to match bet_history
                bet = db.query(Bet).filter(Bet.id == bet_id).first()
                if bet:
                    # Map string status to enum
                    if history_status.lower() == "won":
                        bet.status = BetStatus.WON
                    elif history_status.lower() == "lost":
                        bet.status = BetStatus.LOST
                    elif history_status.lower() == "cancelled":
                        bet.status = BetStatus.CANCELLED

                    bet.result_amount = result_amount or 0
                    bet.settled_at = settled_at

                    synced_bets += 1
                    logger.info(f"✅ Updated bet {bet_id[:8]}... to {bet.status.value}")

                    # Track parlay IDs that need to be recalculated
                    if parlay_id:
                        parlay_ids_to_check.add(parlay_id)
                else:
                    logger.error(f"❌ Bet {bet_id[:8]}... not found in bets table")

            # Sync individual parlay bets
            for parlay_row in mismatched_parlays:
                parlay_id = parlay_row[0]
                user_id = parlay_row[1]
                current_status = parlay_row[3]
                history_status = parlay_row[4]
                result_amount = parlay_row[5]
                settled_at = parlay_row[6]

                logger.info(
                    f"Syncing parlay {parlay_id[:8]}... (user {user_id}): "
                    f"{current_status} → {history_status}"
                )

                # Update the parlay record to match bet_history
                parlay = db.query(ParlayBet).filter(ParlayBet.id == parlay_id).first()
                if parlay:
                    # Map string status to enum
                    if history_status.lower() == "won":
                        parlay.status = BetStatus.WON
                    elif history_status.lower() == "lost":
                        parlay.status = BetStatus.LOST
                    elif history_status.lower() == "cancelled":
                        parlay.status = BetStatus.CANCELLED

                    parlay.result_amount = result_amount or 0
                    parlay.settled_at = settled_at

                    synced_parlays += 1
                    logger.info(
                        f"✅ Updated parlay {parlay_id[:8]}... to {parlay.status.value}"
                    )
                else:
                    logger.error(
                        f"❌ Parlay {parlay_id[:8]}... not found in parlay_bets table"
                    )

            # Update parlay statuses based on leg results
            for parlay_id in parlay_ids_to_check:
                parlay = db.query(ParlayBet).filter(ParlayBet.id == parlay_id).first()
                if parlay and parlay.status == BetStatus.PENDING:
                    # Get all legs for this parlay
                    legs = db.query(Bet).filter(Bet.parlay_id == parlay_id).all()

                    # Check if all legs are settled
                    all_settled = all(leg.status != BetStatus.PENDING for leg in legs)

                    if all_settled:
                        # Check if all legs won
                        all_won = all(leg.status == BetStatus.WON for leg in legs)
                        any_lost = any(leg.status == BetStatus.LOST for leg in legs)

                        if all_won:
                            parlay.status = BetStatus.WON
                            parlay.result_amount = parlay.amount + parlay.potential_win
                            logger.info(
                                f"✅ Parlay {parlay_id[:8]}... WON - all legs won"
                            )
                        elif any_lost:
                            parlay.status = BetStatus.LOST
                            parlay.result_amount = 0
                            logger.info(
                                f"❌ Parlay {parlay_id[:8]}... LOST - at least one leg lost"
                            )
                        else:  # Some cancelled
                            parlay.status = BetStatus.CANCELLED
                            parlay.result_amount = (
                                parlay.amount
                            )  # Return original stake
                            logger.info(
                                f"🚫 Parlay {parlay_id[:8]}... CANCELLED - legs cancelled"
                            )

                        parlay.settled_at = datetime.utcnow()
                        synced_parlays += 1

            # Commit all changes
            db.commit()
            logger.info(
                f"🎉 Successfully synced {synced_bets} bet legs and {synced_parlays} parlays!"
            )

            return {
                "success": True,
                "message": f"Successfully synced {synced_bets} bet legs and {synced_parlays} parlays",
                "synced_count": synced_bets + synced_parlays,
                "synced_bets": synced_bets,
                "synced_parlays": synced_parlays,
                "total_found": total_mismatched,
            }

        except Exception as e:
            db.rollback()
            logger.error(f"❌ Error fixing bet status sync: {e}")
            raise
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Bet status sync fix failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Bet status sync fix failed: {str(e)}"
        )


@app.get("/api/admin/bets/debug")
async def debug_bet_status(admin_user: dict = Depends(require_admin)):
    """Debug bet status in production database (Admin only)"""
    try:
        logger.info("🔍 Debug bet status triggered via admin endpoint")

        from sqlalchemy import text
        from app.models.database_models import Bet, BetStatus, BetHistory, ParlayBet
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            # Get all PENDING bets
            pending_query = """
            SELECT b.id, b.user_id, b.home_team, b.away_team, b.status, b.placed_at
            FROM bets b
            WHERE b.status = 'PENDING'
            ORDER BY b.placed_at DESC
            """
            result = db.execute(text(pending_query))
            pending_bets = result.fetchall()

            # Get Cardinals-related bets (both PENDING and settled)
            cardinals_query = """
            SELECT b.id, b.user_id, b.home_team, b.away_team, b.status, b.placed_at
            FROM bets b
            WHERE (LOWER(b.home_team) LIKE '%cardinal%' OR LOWER(b.away_team) LIKE '%cardinal%')
            ORDER BY b.placed_at DESC
            LIMIT 10
            """
            result = db.execute(text(cardinals_query))
            cardinals_bets = result.fetchall()

            # Get recent bet_history records for Cardinals bets
            cardinals_history = []
            for bet in cardinals_bets:
                bet_id = bet[0]
                history_query = """
                SELECT bh.action, bh.old_status, bh.new_status, bh.amount, bh.timestamp
                FROM bet_history bh
                WHERE bh.bet_id = :bet_id
                ORDER BY bh.timestamp DESC
                LIMIT 3
                """
                history_result = db.execute(text(history_query), {"bet_id": bet_id})
                history_records = history_result.fetchall()
                cardinals_history.append(
                    {
                        "bet_id": bet_id[:8] + "...",
                        "teams": f"{bet[2]} vs {bet[3]}",
                        "status": bet[4],
                        "history": [
                            {
                                "action": record[0],
                                "old_status": record[1],
                                "new_status": record[2],
                                "amount": record[3],
                                "timestamp": str(record[4]),
                            }
                            for record in history_records
                        ],
                    }
                )

            # Run the exact sync query to see what would be synced
            sync_query = """
            SELECT DISTINCT
                b.id,
                b.user_id,
                b.parlay_id,
                b.status as current_status,
                bh.new_status as history_status,
                bh.amount as result_amount,
                bh.timestamp as settled_at
            FROM bets b
            JOIN bet_history bh ON b.id = bh.bet_id
            WHERE b.status = 'PENDING'
            AND bh.action = 'settled'
            AND bh.new_status IN ('won', 'lost', 'cancelled')
            ORDER BY bh.timestamp DESC
            """
            result = db.execute(text(sync_query))
            sync_candidates = result.fetchall()

            return {
                "success": True,
                "pending_bets": [
                    {
                        "bet_id": bet[0][:8] + "...",
                        "teams": f"{bet[2]} vs {bet[3]}",
                        "status": bet[4],
                        "placed_at": str(bet[5]),
                    }
                    for bet in pending_bets
                ],
                "cardinals_bets": cardinals_history,
                "sync_candidates": [
                    {
                        "bet_id": bet[0][:8] + "...",
                        "current_status": bet[3],
                        "history_status": bet[4],
                        "settled_at": str(bet[6]),
                    }
                    for bet in sync_candidates
                ],
                "counts": {
                    "pending_bets": len(pending_bets),
                    "cardinals_bets": len(cardinals_bets),
                    "sync_candidates": len(sync_candidates),
                },
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Debug bet status failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Debug bet status failed: {str(e)}"
        )


@app.post("/api/admin/bets/manual-verify")
async def manual_verify_bet(request: dict, admin_user: dict = Depends(require_admin)):
    """Manually verify and settle a specific bet (Admin only)"""
    try:
        bet_id = request.get("bet_id")
        if not bet_id:
            raise HTTPException(status_code=400, detail="bet_id is required")

        logger.info(f"🔧 Manual bet verification for bet {bet_id[:8]}...")

        from sqlalchemy import text
        from app.models.database_models import Bet, BetStatus, BetHistory
        from app.core.database import SessionLocal
        from datetime import datetime

        db = SessionLocal()
        try:
            # Get the bet
            bet = db.query(Bet).filter(Bet.id == bet_id).first()
            if not bet:
                raise HTTPException(status_code=404, detail="Bet not found")

            if bet.status != BetStatus.PENDING:
                return {
                    "success": False,
                    "message": f"Bet {bet_id[:8]}... is already settled ({bet.status.value})",
                }

            # Get the game for this bet
            if not bet.game_id:
                raise HTTPException(
                    status_code=400, detail="Bet has no associated game"
                )

            # Check if game has finished and get the result
            game_query = """
            SELECT home_team, away_team, home_score, away_score, status, commence_time
            FROM games
            WHERE id = :game_id
            """
            result = db.execute(text(game_query), {"game_id": bet.game_id})
            game = result.fetchone()

            if not game:
                raise HTTPException(status_code=404, detail="Game not found")

            home_team, away_team, home_score, away_score, game_status, commence_time = (
                game
            )

            # Check if game is completed
            if game_status != "completed" or home_score is None or away_score is None:
                return {
                    "success": False,
                    "message": f"Game {home_team} vs {away_team} is not completed yet (status: {game_status})",
                    "game_info": {
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_score": home_score,
                        "away_score": away_score,
                        "status": game_status,
                    },
                }

            # Determine bet result based on bet type and selection
            bet_won = False
            if bet.bet_type.value == "moneyline":
                # For moneyline, check if selected team won
                if bet.selection == home_team and home_score > away_score:
                    bet_won = True
                elif bet.selection == away_team and away_score > home_score:
                    bet_won = True
            elif bet.bet_type.value == "spread":
                # For spread bets, need to check against the line
                if bet.selection == home_team:
                    adjusted_home_score = home_score + (bet.line_value or 0)
                    bet_won = adjusted_home_score > away_score
                elif bet.selection == away_team:
                    adjusted_away_score = away_score + (bet.line_value or 0)
                    bet_won = adjusted_away_score > home_score

            # Determine final status and amount
            if bet_won:
                final_status = BetStatus.WON
                result_amount = bet.amount + bet.potential_win
            else:
                final_status = BetStatus.LOST
                result_amount = 0

            # Update bet status
            old_status = bet.status.value
            bet.status = final_status
            bet.result_amount = result_amount
            bet.settled_at = datetime.utcnow()

            # Create bet_history record
            bet_history = BetHistory(
                bet_id=bet.id,
                action="settled",
                old_status=old_status,
                new_status=final_status.value,
                amount=result_amount,
                timestamp=datetime.utcnow(),
            )
            db.add(bet_history)

            # Commit changes
            db.commit()

            logger.info(
                f"✅ Manually settled bet {bet_id[:8]}... as {final_status.value}"
            )

            return {
                "success": True,
                "message": f"Bet {bet_id[:8]}... manually settled as {final_status.value}",
                "bet_info": {
                    "bet_id": bet_id[:8] + "...",
                    "teams": f"{home_team} vs {away_team}",
                    "selection": bet.selection,
                    "bet_type": bet.bet_type.value,
                    "old_status": old_status,
                    "new_status": final_status.value,
                    "result_amount": result_amount,
                },
                "game_info": {
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": home_score,
                    "away_score": away_score,
                    "final_score": f"{home_team} {home_score} - {away_score} {away_team}",
                },
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Manual bet verification failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Manual bet verification failed: {str(e)}"
        )


@app.post("/api/admin/games/manual-update")
async def manual_update_game(request: dict, admin_user: dict = Depends(require_admin)):
    """Manually update game result (Admin only)"""
    try:
        home_team = request.get("home_team")
        away_team = request.get("away_team")
        home_score = request.get("home_score")
        away_score = request.get("away_score")

        if not all(
            [home_team, away_team, home_score is not None, away_score is not None]
        ):
            raise HTTPException(
                status_code=400,
                detail="home_team, away_team, home_score, and away_score are required",
            )

        logger.info(
            f"🔧 Manual game update: {home_team} {home_score} - {away_score} {away_team}"
        )

        from sqlalchemy import text
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            # Find the game
            game_query = """
            SELECT id, home_team, away_team, status, home_score, away_score
            FROM games
            WHERE home_team = :home_team AND away_team = :away_team
            ORDER BY commence_time DESC
            LIMIT 1
            """
            result = db.execute(
                text(game_query), {"home_team": home_team, "away_team": away_team}
            )
            game = result.fetchone()

            if not game:
                raise HTTPException(status_code=404, detail="Game not found")

            game_id = game[0]
            current_status = game[3]
            current_home_score = game[4]
            current_away_score = game[5]

            # Update the game
            update_query = """
            UPDATE games
            SET home_score = :home_score,
                away_score = :away_score,
                status = 'completed',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :game_id
            """

            db.execute(
                text(update_query),
                {
                    "game_id": game_id,
                    "home_score": home_score,
                    "away_score": away_score,
                },
            )

            db.commit()

            logger.info(
                f"✅ Updated game {game_id[:8]}... to completed with final score"
            )

            return {
                "success": True,
                "message": f"Game updated successfully",
                "game_info": {
                    "game_id": game_id[:8] + "...",
                    "teams": f"{home_team} vs {away_team}",
                    "old_status": current_status,
                    "new_status": "completed",
                    "old_score": f"{current_home_score or 0}-{current_away_score or 0}",
                    "new_score": f"{home_score}-{away_score}",
                    "final_result": f"{home_team} {home_score} - {away_score} {away_team}",
                },
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Manual game update failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Manual game update failed: {str(e)}"
        )


@app.post("/api/admin/parlays/fix-game-associations")
async def fix_parlay_game_associations(admin_user: dict = Depends(require_admin)):
    """Fix parlay legs missing game associations (Admin only)"""
    try:
        logger.info("🔧 Fixing parlay leg game associations...")

        from sqlalchemy import text
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            # Find parlay legs without game associations
            orphaned_legs_query = """
            SELECT b.id, b.selection, b.bet_type, b.parlay_id
            FROM bets b
            JOIN parlay_bets pb ON b.parlay_id = pb.id
            WHERE b.game_id IS NULL
            AND b.status = 'PENDING'
            AND pb.status = 'PENDING'
            """
            result = db.execute(text(orphaned_legs_query))
            orphaned_legs = result.fetchall()

            if not orphaned_legs:
                return {
                    "success": True,
                    "message": "No orphaned parlay legs found",
                    "fixed_count": 0,
                }

            fixed_count = 0
            fixes = []

            for leg in orphaned_legs:
                leg_id, selection, bet_type, parlay_id = leg

                # Try to match leg to a game based on selection
                if bet_type == "moneyline":
                    # For moneyline, selection is team name
                    game_query = """
                    SELECT id, home_team, away_team
                    FROM games
                    WHERE (home_team = :team OR away_team = :team)
                    AND status IN ('SCHEDULED', 'completed')
                    ORDER BY commence_time DESC
                    LIMIT 1
                    """
                    game_result = db.execute(text(game_query), {"team": selection})
                    game = game_result.fetchone()

                    if game:
                        game_id, home_team, away_team = game

                        # Update the bet with game association
                        update_query = """
                        UPDATE bets
                        SET game_id = :game_id,
                            home_team = :home_team,
                            away_team = :away_team
                        WHERE id = :bet_id
                        """
                        db.execute(
                            text(update_query),
                            {
                                "bet_id": leg_id,
                                "game_id": game_id,
                                "home_team": home_team,
                                "away_team": away_team,
                            },
                        )

                        fixed_count += 1
                        fixes.append(
                            {
                                "leg_id": leg_id[:8] + "...",
                                "selection": selection,
                                "bet_type": bet_type,
                                "matched_game": f"{home_team} vs {away_team}",
                                "game_id": game_id[:8] + "...",
                            }
                        )

            db.commit()

            logger.info(f"✅ Fixed {fixed_count} parlay leg game associations")

            return {
                "success": True,
                "message": f"Fixed {fixed_count} parlay leg game associations",
                "fixed_count": fixed_count,
                "fixes": fixes,
                "orphaned_legs_found": len(orphaned_legs),
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Fix parlay game associations failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Fix parlay game associations failed: {str(e)}"
        )


@app.post("/api/admin/parlays/manual-fix-specific")
async def manual_fix_specific_parlay_legs(admin_user: dict = Depends(require_admin)):
    """Manually fix the specific parlay legs we know about (Admin only)"""
    try:
        logger.info("🔧 Manually fixing specific parlay legs...")

        from sqlalchemy import text
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            fixes = []

            # Fix Cincinnati Reds leg - should match Cardinals vs Reds game
            reds_query = """
            SELECT b.id
            FROM bets b
            JOIN parlay_bets pb ON b.parlay_id = pb.id
            WHERE b.selection = 'Cincinnati Reds'
            AND b.bet_type::text = 'moneyline'
            AND b.game_id IS NULL
            AND b.status = 'PENDING'
            """
            result = db.execute(text(reds_query))
            reds_leg = result.fetchone()

            if reds_leg:
                # Find Cardinals vs Reds game
                game_query = """
                SELECT id, home_team, away_team
                FROM games
                WHERE (home_team LIKE '%Cardinal%' AND away_team LIKE '%Red%')
                OR (home_team LIKE '%Red%' AND away_team LIKE '%Cardinal%')
                ORDER BY commence_time DESC
                LIMIT 1
                """
                game_result = db.execute(text(game_query))
                game = game_result.fetchone()

                if game:
                    game_id, home_team, away_team = game

                    update_query = """
                    UPDATE bets
                    SET game_id = :game_id,
                        home_team = :home_team,
                        away_team = :away_team
                    WHERE id = :bet_id
                    """
                    db.execute(
                        text(update_query),
                        {
                            "bet_id": reds_leg[0],
                            "game_id": game_id,
                            "home_team": home_team,
                            "away_team": away_team,
                        },
                    )

                    fixes.append(
                        {
                            "leg_id": reds_leg[0][:8] + "...",
                            "selection": "Cincinnati Reds",
                            "matched_game": f"{home_team} vs {away_team}",
                            "game_id": game_id[:8] + "...",
                        }
                    )

            # Fix Chicago Cubs leg - find Cubs game
            cubs_query = """
            SELECT b.id
            FROM bets b
            JOIN parlay_bets pb ON b.parlay_id = pb.id
            WHERE b.selection = 'Chicago Cubs'
            AND b.bet_type::text = 'moneyline'
            AND b.game_id IS NULL
            AND b.status = 'PENDING'
            """
            result = db.execute(text(cubs_query))
            cubs_leg = result.fetchone()

            if cubs_leg:
                # Find Cubs game
                cubs_game_query = """
                SELECT id, home_team, away_team
                FROM games
                WHERE home_team LIKE '%Cubs%' OR away_team LIKE '%Cubs%'
                ORDER BY commence_time DESC
                LIMIT 1
                """
                game_result = db.execute(text(cubs_game_query))
                game = game_result.fetchone()

                if game:
                    game_id, home_team, away_team = game

                    update_query = """
                    UPDATE bets
                    SET game_id = :game_id,
                        home_team = :home_team,
                        away_team = :away_team
                    WHERE id = :bet_id
                    """
                    db.execute(
                        text(update_query),
                        {
                            "bet_id": cubs_leg[0],
                            "game_id": game_id,
                            "home_team": home_team,
                            "away_team": away_team,
                        },
                    )

                    fixes.append(
                        {
                            "leg_id": cubs_leg[0][:8] + "...",
                            "selection": "Chicago Cubs",
                            "matched_game": f"{home_team} vs {away_team}",
                            "game_id": game_id[:8] + "...",
                        }
                    )

            db.commit()

            return {
                "success": True,
                "message": f"Manually fixed {len(fixes)} specific parlay legs",
                "fixed_count": len(fixes),
                "fixes": fixes,
                "note": "Total bets (O 7.5) require additional context and weren't fixed automatically",
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Manual fix specific parlay legs failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Manual fix specific parlay legs failed: {str(e)}"
        )


@app.post("/api/admin/parlays/force-settle")
async def force_settle_parlay(request: dict, admin_user: dict = Depends(require_admin)):
    """Force settlement of a parlay based on current leg statuses (Admin only)"""
    try:
        parlay_id = request.get("parlay_id")
        if not parlay_id:
            raise HTTPException(status_code=400, detail="parlay_id is required")

        logger.info(f"🔧 Force settling parlay {parlay_id[:8]}...")

        from app.models.simple_unified_bet_model import SimpleUnifiedBet
        from app.models.database_models import BetStatus
        from app.core.database import SessionLocal
        from datetime import datetime

        db = SessionLocal()
        try:
            # First, verify the parlay exists and check its legs
            parlay = (
                db.query(SimpleUnifiedBet)
                .filter(SimpleUnifiedBet.id == parlay_id)
                .first()
            )

            if not parlay:
                raise HTTPException(status_code=404, detail="Parlay not found")

            # Get all legs
            legs = (
                db.query(SimpleUnifiedBet)
                .filter(SimpleUnifiedBet.parent_bet_id == parlay_id)
                .all()
            )

            leg_statuses = {
                "won": sum(1 for leg in legs if leg.status == BetStatus.WON),
                "lost": sum(1 for leg in legs if leg.status == BetStatus.LOST),
                "pushed": sum(1 for leg in legs if leg.status == BetStatus.PUSHED),
                "pending": sum(1 for leg in legs if leg.status == BetStatus.PENDING),
            }

            logger.info(
                f"Parlay {parlay_id[:8]} - Current status: {parlay.status.value}, Legs: {leg_statuses}"
            )

            # If any leg is lost, mark parlay as lost
            if leg_statuses["lost"] > 0 and parlay.status == BetStatus.PENDING:
                logger.info(f"Marking parlay {parlay_id[:8]} as LOST")
                parlay.status = BetStatus.LOST
                parlay.result_amount = 0
                parlay.settled_at = datetime.utcnow()
                db.commit()
                logger.info(f"✅ Parlay {parlay_id[:8]} marked as LOST")

                return {
                    "success": True,
                    "message": f"Parlay {parlay_id[:8]}... marked as LOST",
                    "parlay_id": parlay_id,
                    "leg_statuses": leg_statuses,
                    "action": "settled_as_lost",
                }
            elif parlay.status != BetStatus.PENDING:
                return {
                    "success": True,
                    "message": f"Parlay {parlay_id[:8]}... already settled as {parlay.status.value}",
                    "parlay_id": parlay_id,
                    "leg_statuses": leg_statuses,
                    "action": "already_settled",
                }
            else:
                return {
                    "success": True,
                    "message": f"Parlay {parlay_id[:8]}... not ready to settle",
                    "parlay_id": parlay_id,
                    "leg_statuses": leg_statuses,
                    "action": "not_ready",
                }

        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Force settle parlay failed: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Force settle parlay failed: {str(e)}"
        )


@app.post("/api/admin/parlays/fix-specific-ids")
async def fix_specific_parlay_ids(admin_user: dict = Depends(require_admin)):
    """Fix parlay legs using their specific IDs (Admin only)"""
    try:
        logger.info("🔧 Fixing parlay legs by specific IDs...")

        from sqlalchemy import text
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            fixes = []

            # Fix Cincinnati Reds leg by ID - from the parlay data you shared
            reds_leg_id = "cd675b49-6f0d-4b38-bcd9-89041f0f27b5"

            # Find Cardinals vs Reds game
            game_query = """
            SELECT id, home_team, away_team
            FROM games
            WHERE (home_team LIKE '%Cardinal%' AND away_team LIKE '%Red%')
            OR (home_team LIKE '%Red%' AND away_team LIKE '%Cardinal%')
            ORDER BY commence_time DESC
            LIMIT 1
            """
            game_result = db.execute(text(game_query))
            game = game_result.fetchone()

            if game:
                game_id, home_team, away_team = game

                # Update the Reds leg
                update_query = """
                UPDATE bets
                SET game_id = :game_id,
                    home_team = :home_team,
                    away_team = :away_team
                WHERE id = :bet_id
                """
                db.execute(
                    text(update_query),
                    {
                        "bet_id": reds_leg_id,
                        "game_id": game_id,
                        "home_team": home_team,
                        "away_team": away_team,
                    },
                )

                fixes.append(
                    {
                        "leg_id": reds_leg_id[:8] + "...",
                        "selection": "Cincinnati Reds (by ID)",
                        "matched_game": f"{home_team} vs {away_team}",
                        "game_id": game_id[:8] + "...",
                    }
                )

            # Fix Chicago Cubs leg by ID
            cubs_leg_id = "0056b9d7-ae32-445d-91d2-5d6672e55655"

            # Find Cubs game
            cubs_game_query = """
            SELECT id, home_team, away_team
            FROM games
            WHERE home_team LIKE '%Cubs%' OR away_team LIKE '%Cubs%'
            ORDER BY commence_time DESC
            LIMIT 1
            """
            game_result = db.execute(text(cubs_game_query))
            game = game_result.fetchone()

            if game:
                game_id, home_team, away_team = game

                # Update the Cubs leg
                update_query = """
                UPDATE bets
                SET game_id = :game_id,
                    home_team = :home_team,
                    away_team = :away_team
                WHERE id = :bet_id
                """
                db.execute(
                    text(update_query),
                    {
                        "bet_id": cubs_leg_id,
                        "game_id": game_id,
                        "home_team": home_team,
                        "away_team": away_team,
                    },
                )

                fixes.append(
                    {
                        "leg_id": cubs_leg_id[:8] + "...",
                        "selection": "Chicago Cubs (by ID)",
                        "matched_game": f"{home_team} vs {away_team}",
                        "game_id": game_id[:8] + "...",
                    }
                )

            db.commit()

            return {
                "success": True,
                "message": f"Fixed {len(fixes)} parlay legs by specific IDs",
                "fixed_count": len(fixes),
                "fixes": fixes,
                "note": f"Used hardcoded bet IDs: Reds={reds_leg_id[:8]}..., Cubs={cubs_leg_id[:8]}...",
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Fix specific parlay IDs failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Fix specific parlay IDs failed: {str(e)}"
        )


@app.post("/api/admin/parlays/fix-all-orphaned-legs")
async def fix_all_orphaned_parlay_legs(admin_user: dict = Depends(require_admin)):
    """Fix all parlay legs that don't have game associations (Admin only)"""
    try:
        logger.info("🔧 Fixing all orphaned parlay legs...")

        from sqlalchemy import text
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            # Find all parlay legs without game associations
            orphaned_query = """
            SELECT b.id, b.selection, b.bet_type, b.parlay_id
            FROM bets b
            WHERE b.bet_type::text IN ('moneyline', 'spread', 'total')
            AND b.parlay_id IS NOT NULL
            AND b.game_id IS NULL
            ORDER BY b.placed_at DESC
            """
            orphaned_result = db.execute(text(orphaned_query))
            orphaned_legs = orphaned_result.fetchall()

            if not orphaned_legs:
                return {
                    "status": "success",
                    "message": "No orphaned parlay legs found",
                    "fixed_legs": [],
                }

            logger.info(f"Found {len(orphaned_legs)} orphaned parlay legs")

            fixed_legs = []
            unmatched_legs = []

            for leg in orphaned_legs:
                bet_id, selection, bet_type, parlay_id = leg
                logger.info(
                    f"Processing leg {bet_id[:8]}... - {selection} ({bet_type})"
                )

                # Extract team names from selection
                team_name = None

                if bet_type == "moneyline":
                    # For moneyline, selection is just the team name
                    team_name = selection.strip()
                elif bet_type == "spread":
                    # For spread, extract team from "Detroit Tigers +7.5" format
                    if "+" in selection or "-" in selection:
                        # Split on + or - and take the first part
                        import re

                        match = re.match(r"^(.+?)\s*[+-]", selection)
                        if match:
                            team_name = match.group(1).strip()
                elif bet_type == "total":
                    # For total bets, we need to find the game differently
                    # Look for "Over X.X" or "Under X.X" in selection
                    # We'll need to find recent games and match by timing/context
                    logger.info(f"Total bet detected: {selection} - skipping for now")
                    continue

                if not team_name:
                    logger.warning(
                        f"Could not extract team name from selection: {selection}"
                    )
                    unmatched_legs.append(
                        {
                            "bet_id": bet_id[:8] + "...",
                            "selection": selection,
                            "bet_type": bet_type,
                            "reason": "Could not extract team name",
                        }
                    )
                    continue

                # Find matching game
                game_query = """
                SELECT id, home_team, away_team, commence_time
                FROM games
                WHERE (home_team ILIKE %s OR away_team ILIKE %s)
                AND commence_time >= NOW() - INTERVAL '7 days'
                ORDER BY commence_time DESC
                LIMIT 1
                """

                # Create search pattern
                search_pattern = f"%{team_name}%"

                game_result = db.execute(
                    text(game_query), (search_pattern, search_pattern)
                )
                game = game_result.fetchone()

                if game:
                    game_id, home_team, away_team, commence_time = game

                    # Update the bet with game information
                    update_query = """
                    UPDATE bets
                    SET game_id = :game_id,
                        home_team = :home_team,
                        away_team = :away_team
                    WHERE id = :bet_id
                    """
                    db.execute(
                        text(update_query),
                        {
                            "bet_id": bet_id,
                            "game_id": game_id,
                            "home_team": home_team,
                            "away_team": away_team,
                        },
                    )

                    fixed_legs.append(
                        {
                            "bet_id": bet_id[:8] + "...",
                            "selection": selection,
                            "bet_type": bet_type,
                            "matched_team": team_name,
                            "game": f"{home_team} vs {away_team}",
                            "game_id": game_id[:8] + "...",
                            "commence_time": str(commence_time),
                        }
                    )

                    logger.info(
                        f"✅ Fixed leg {bet_id[:8]}... -> {home_team} vs {away_team}"
                    )

                else:
                    logger.warning(f"No game found for team: {team_name}")
                    unmatched_legs.append(
                        {
                            "bet_id": bet_id[:8] + "...",
                            "selection": selection,
                            "bet_type": bet_type,
                            "extracted_team": team_name,
                            "reason": "No matching game found",
                        }
                    )

            # Commit all changes
            db.commit()

            return {
                "status": "success",
                "message": f"Fixed {len(fixed_legs)} orphaned parlay legs",
                "fixed_legs": fixed_legs,
                "unmatched_legs": unmatched_legs,
                "total_processed": len(orphaned_legs),
            }

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error fixing orphaned parlay legs: {e}")
        raise HTTPException(
            status_code=500, detail=f"Fix orphaned parlay legs failed: {str(e)}"
        )


@app.options("/api/admin/parlays/fix-all-orphaned-legs")
async def options_fix_all_orphaned_parlay_legs():
    """Handle CORS preflight for fix all orphaned parlay legs"""
    return {}


@app.options("/api/admin/bets/verification/config")
async def options_verification_config():
    """Handle CORS preflight for verification config"""
    return {}


@app.post("/api/admin/bets/verification/config")
async def update_verification_config(
    config: dict, admin_user: dict = Depends(require_admin)
):
    """Update bet verification configuration (Admin only)"""
    try:
        result = bet_scheduler.update_config(config)
        return {"status": "success", "config": result}
    except Exception as e:
        logger.error(f"Error updating verification config: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to update verification config"
        )


@app.options("/api/admin/bets/verification/reset-stats")
async def options_reset_verification_stats():
    """Handle CORS preflight for reset verification stats"""
    return {}


@app.post("/api/admin/bets/verification/reset-stats")
async def reset_verification_stats(admin_user: dict = Depends(require_admin)):
    """Reset bet verification statistics (Admin only)"""
    try:
        result = bet_scheduler.reset_stats()
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Error resetting verification stats: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to reset verification stats"
        )


@app.options("/api/admin/games/sync")
async def options_sync_games():
    """Handle CORS preflight for game sync"""
    return {}


@app.post("/api/admin/games/sync")
async def sync_games(admin_user: dict = Depends(require_admin)):
    """Manually sync game data from Odds API (Admin only)"""
    try:
        from app.services.game_sync_service import game_sync_service

        result = await game_sync_service.sync_game_scores(days_back=3)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Error syncing games: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync games")


@app.post("/api/admin/games/sync-upcoming")
async def sync_upcoming_games(admin_user: dict = Depends(require_admin)):
    """Sync upcoming games from Odds API to populate real game data (Admin only)"""
    try:
        from app.services.game_sync_service import game_sync_service

        result = await game_sync_service.sync_upcoming_games(days_ahead=7)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Error syncing upcoming games: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync upcoming games")


@app.get("/api/admin/games/test-api")
async def test_odds_api(admin_user: dict = Depends(require_admin)):
    """Test Odds API connectivity and available games (Admin only)"""
    try:
        from app.services.odds_api_service import OddsAPIService
        from app.core.config import settings

        if not settings.ODDS_API_KEY:
            return {"status": "error", "message": "No API key configured"}

        # Test with a small sample
        async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
            # Try MLB first (most likely to have games)
            games = await odds_service.get_odds("baseball_mlb")

            return {
                "status": "success",
                "mlb_games_found": len(games),
                "sample_games": [
                    {
                        "id": game.id,
                        "teams": f"{game.away_team} @ {game.home_team}",
                        "commence_time": game.commence_time.isoformat(),
                    }
                    for game in games[:3]  # First 3 games
                ],
            }
    except Exception as e:
        logger.error(f"Error testing odds API: {e}")
        return {"status": "error", "error": str(e)}


# Sports Betting API Endpoints
@app.options("/api/bets/place")
async def options_place_bet():
    """Handle CORS preflight for bet placement"""
    return {}


@app.post("/api/bets/place")
async def place_bet(
    bet_request: PlaceBetRequest, current_user: dict = Depends(get_current_user)
):
    """Place a single sports bet"""
    try:
        result = await simple_unified_bet_service.place_bet(
            user_id=current_user.get("id") or current_user.get("user_id"),
            bet_data=bet_request,
        )

        if result.get("success"):
            return {
                "status": "success",
                "bet": result.get("bet"),
                "message": result.get("message", "Bet placed successfully"),
            }
        else:
            raise HTTPException(
                status_code=400, detail=result.get("error", "Failed to place bet")
            )

    except Exception as e:
        logger.error(f"Error placing bet: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to place bet: {str(e)}")


@app.options("/api/bets/parlay")
async def options_place_parlay():
    """Handle CORS preflight for parlay placement"""
    return {}


@app.post("/api/bets/parlay")
async def place_parlay(
    parlay_request: PlaceParlayRequest, current_user: dict = Depends(get_current_user)
):
    """Place a parlay bet with multiple legs"""
    try:
        result = await simple_unified_bet_service.place_parlay(
            user_id=current_user.get("id") or current_user.get("user_id"),
            parlay_data=parlay_request,
        )

        if result.get("success"):
            return {
                "status": "success",
                "parlay": result.get("parlay"),
                "legs": result.get("leg_ids", []),
                "message": result.get("message", "Parlay placed successfully"),
            }
        else:
            raise HTTPException(
                status_code=400, detail=result.get("error", "Failed to place parlay")
            )

    except Exception as e:
        logger.error(f"Error placing parlay: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to place parlay: {str(e)}")


@app.options("/api/bets/parlays")
async def options_get_parlays():
    """Handle CORS preflight for getting parlays"""
    return {}


@app.get("/api/bets/parlays")
async def get_parlays(current_user: dict = Depends(get_current_user)):
    """Get user's parlay bets using unified service"""
    try:
        # Get all user bets and filter for parlays only
        bets = await simple_unified_bet_service.get_user_bets(
            current_user.get("id") or current_user.get("user_id"),
            include_legs=False,  # Only get parent parlays, not legs
        )

        # Filter for parlay bets only
        parlays = []
        for bet in bets:
            if bet.get("is_parlay"):
                # Get legs for this parlay
                parlay_with_legs = await simple_unified_bet_service.get_bet_by_id(
                    bet["id"]
                )
                if parlay_with_legs:
                    parlays.append(parlay_with_legs)

        return {"status": "success", "parlays": parlays}

    except Exception as e:
        logger.error(f"Error fetching parlays: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch parlays: {str(e)}"
        )


@app.get("/api/bets/parlay/{parlay_id}")
async def get_parlay_details(
    parlay_id: str, current_user: dict = Depends(get_current_user)
):
    """Get specific parlay details using unified service"""
    try:
        parlay = await simple_unified_bet_service.get_bet_by_id(parlay_id)

        if not parlay:
            raise HTTPException(status_code=404, detail="Parlay not found")

        # Verify the parlay belongs to the current user
        if parlay["user_id"] != (current_user.get("id") or current_user.get("user_id")):
            raise HTTPException(status_code=403, detail="Access denied")

        return {"status": "success", "parlay": parlay}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching parlay {parlay_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch parlay details: {str(e)}"
        )


@app.options("/api/bets/history")
async def options_bet_history():
    """Handle CORS preflight for bet history"""
    return {}


@app.post("/api/bets/history")
async def get_bet_history(
    query: BetHistoryQuery, current_user: dict = Depends(get_current_user)
):
    """Get user bet history with filtering using unified service"""
    try:
        # Get all user bets from unified service
        bets = await simple_unified_bet_service.get_user_bets(
            current_user.get("id") or current_user.get("user_id"),
            include_legs=False,  # Exclude parlay legs, only show parent bets
        )

        # Apply filters
        filtered_bets = []
        for bet in bets:
            # Status filter
            if query.status and bet.get("status") != query.status.lower():
                continue

            # Bet type filter
            if query.bet_type and bet.get("bet_type") != query.bet_type.lower():
                continue

            # Date filters (if provided)
            if query.start_date or query.end_date:
                placed_at = bet.get("placed_at")
                if placed_at:
                    from datetime import datetime

                    if isinstance(placed_at, str):
                        bet_date = datetime.fromisoformat(
                            placed_at.replace("Z", "+00:00")
                        ).date()
                    else:
                        bet_date = placed_at.date()

                    if query.start_date:
                        start_date = datetime.fromisoformat(query.start_date).date()
                        if bet_date < start_date:
                            continue

                    if query.end_date:
                        end_date = datetime.fromisoformat(query.end_date).date()
                        if bet_date > end_date:
                            continue

            filtered_bets.append(bet)

        # Apply pagination
        total = len(filtered_bets)
        start_idx = query.offset
        end_idx = start_idx + query.limit
        paginated_bets = filtered_bets[start_idx:end_idx]

        # Transform to match expected format (add parlay_id for backward compatibility)
        history = []
        for bet in paginated_bets:
            history_bet = dict(bet)
            # Map parent_bet_id to parlay_id for backward compatibility
            if bet.get("parent_bet_id"):
                history_bet["parlay_id"] = bet["parent_bet_id"]
            else:
                history_bet["parlay_id"] = None
            history.append(history_bet)

        return {
            "status": "success",
            "history": history,
            "total": total,
            "offset": query.offset,
            "limit": query.limit,
        }
    except Exception as e:
        logger.error(f"Error fetching bet history: {e}")
        return {
            "status": "error",
            "error": str(e),
            "history": [],
            "total": 0,
            "offset": query.offset,
            "limit": query.limit,
        }


@app.options("/api/bets/stats")
async def options_bet_stats():
    """Handle CORS preflight for bet statistics"""
    return {}


@app.get("/api/bets/stats")
async def get_bet_stats(current_user: dict = Depends(get_current_user)):
    """Get comprehensive betting statistics for user"""
    user_id = current_user.get("id") or current_user.get("user_id")
    logger.info(f"Getting bet stats for user {user_id}")

    try:
        stats = await simple_unified_bet_service.get_user_stats(user_id)

        # Format stats for frontend compatibility
        formatted_stats = {
            "total_bets": stats.get("total_bets", 0),
            "total_wagered": stats.get("total_wagered", 0.0),
            "total_winnings": stats.get("total_won", 0.0),
            "win_rate": stats.get("win_rate", 0.0) / 100,  # Convert to decimal
            "roi": (
                (stats.get("profit_loss", 0.0) / stats.get("total_wagered", 1.0))
                if stats.get("total_wagered", 0) > 0
                else 0.0
            ),
            "average_odds": -110,  # Default American odds
            "favorite_sport": "NFL",
            "favorite_bet_type": "moneyline",
            "current_streak": {"type": "mixed", "count": 0},
            "monthly_summary": {
                "bets": stats.get("total_bets", 0),
                "wagered": stats.get("total_wagered", 0.0),
                "winnings": stats.get("total_won", 0.0),
                "roi": (
                    (stats.get("profit_loss", 0.0) / stats.get("total_wagered", 1.0))
                    if stats.get("total_wagered", 0) > 0
                    else 0.0
                ),
            },
            # Unified structure stats
            "straight_bets": stats.get("straight_bets", 0),
            "parlay_bets": stats.get("parlay_bets", 0),
            "live_bets": stats.get("live_bets", 0),
            "yetai_bets": stats.get("yetai_bets", 0),
        }

        logger.info(f"Successfully retrieved formatted stats: {formatted_stats}")
        return {"status": "success", "stats": formatted_stats}
    except Exception as e:
        logger.error(f"Error fetching bet stats: {e}")
        return {
            "status": "error",
            "error": f"Failed to fetch stats: {str(e)}",
            "stats": {},
        }


@app.options("/api/bets/share")
async def options_share_bet():
    """Handle CORS preflight for bet sharing"""
    return {}


@app.post("/api/bets/share")
async def share_bet(
    share_request: ShareBetRequest, current_user: dict = Depends(get_current_user)
):
    """Share a bet with other users"""
    if is_service_available("bet_sharing_service_db"):
        try:
            sharing_service = get_service("bet_sharing_service_db")
            result = await sharing_service.share_bet(
                user_id=current_user.get("id") or current_user.get("user_id"),
                bet_id=share_request.bet_id,
                message=share_request.message,
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
            "user_id": current_user.get("id") or current_user.get("user_id"),
            "message": share_request.message,
            "share_url": f"https://yetai.app/shared-bet/{share_request.bet_id}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "message": "Mock bet shared - sharing service unavailable",
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
                    "amount": 200.0,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "message": "Mock shared bets - sharing service unavailable",
    }


@app.options("/api/bets/shared/{share_id}")
async def options_delete_shared_bet():
    """Handle CORS preflight for deleting shared bet"""
    return {}


@app.delete("/api/bets/shared/{share_id}")
async def delete_shared_bet(
    share_id: str, current_user: dict = Depends(get_current_user)
):
    """Delete a shared bet"""
    if is_service_available("bet_sharing_service_db"):
        try:
            sharing_service = get_service("bet_sharing_service_db")
            await sharing_service.delete_shared_bet(
                share_id, current_user.get("id") or current_user.get("user_id")
            )
            return {"status": "success", "message": f"Shared bet {share_id} deleted"}
        except Exception as e:
            logger.error(f"Error deleting shared bet {share_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete shared bet")

    # Mock deletion response
    return {
        "status": "success",
        "message": f"Mock deletion of shared bet {share_id} - sharing service unavailable",
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
            result = await bet_service.cancel_bet(
                bet_id, current_user.get("id") or current_user.get("user_id")
            )
            return {
                "status": "success",
                "message": f"Bet {bet_id} cancelled",
                "result": result,
            }
        except Exception as e:
            logger.error(f"Error cancelling bet {bet_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to cancel bet")

    # Mock cancellation response
    return {
        "status": "success",
        "message": f"Mock cancellation of bet {bet_id} - bet service unavailable",
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
            "payout": (
                round(random.uniform(50, 500), 2) if random.choice([True, False]) else 0
            ),
            "message": "Simulated bet outcome for testing",
        },
        "message": "Mock bet simulation - bet service unavailable",
    }


# Fantasy Sports API Endpoints
@app.options("/api/fantasy/accounts")
async def options_fantasy_accounts():
    """Handle CORS preflight for fantasy accounts"""
    return {}


@app.get("/api/fantasy/accounts")
async def get_fantasy_accounts(current_user: dict = Depends(get_current_user)):
    """Get connected fantasy accounts"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.get_user_connections(
            current_user.get("id") or current_user.get("user_id")
        )
        return result
    except Exception as e:
        logger.error(
            f"Error getting fantasy accounts for user {current_user['user_id']}: {e}"
        )
        raise HTTPException(status_code=500, detail="Failed to get fantasy accounts")


@app.options("/api/fantasy/leagues")
async def options_fantasy_leagues():
    """Handle CORS preflight for fantasy leagues"""
    return {}


@app.get("/api/fantasy/leagues")
async def get_fantasy_leagues(current_user: dict = Depends(get_current_user)):
    """Get fantasy leagues for user"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.get_user_leagues(
            current_user.get("id") or current_user.get("user_id")
        )
        return result
    except Exception as e:
        logger.error(
            f"Error getting fantasy leagues for user {current_user['user_id']}: {e}"
        )
        raise HTTPException(status_code=500, detail="Failed to get fantasy leagues")


@app.options("/api/fantasy/connect")
async def options_fantasy_connect():
    """Handle CORS preflight for fantasy platform connection"""
    return {}


@app.post("/api/fantasy/connect")
async def connect_fantasy_platform(
    connect_request: FantasyConnectRequest,
    current_user: dict = Depends(get_current_user),
):
    """Connect to a fantasy platform (Sleeper, ESPN, etc.)"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.connect_platform(
            user_id=current_user.get("id") or current_user.get("user_id"),
            platform=connect_request.platform,
            credentials=connect_request.credentials,
        )
        return result
    except ValueError as e:
        logger.error(f"Validation error connecting to {connect_request.platform}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error connecting to {connect_request.platform}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to {connect_request.platform}: {str(e)}",
        )


@app.options("/api/fantasy/roster/{league_id}")
async def options_fantasy_roster():
    """Handle CORS preflight for fantasy roster"""
    return {}


@app.get("/api/fantasy/roster/{league_id}")
async def get_fantasy_roster(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Get fantasy roster for a specific league - REAL DATA ONLY"""
    logger.info(
        f"🔍 ROSTER ENDPOINT CALLED - League: {league_id}, User: {current_user['user_id']}"
    )

    service_available = is_service_available("fantasy_pipeline")
    logger.info(f"🔍 FANTASY_PIPELINE SERVICE AVAILABLE: {service_available}")

    if not service_available:
        logger.error("🚨 FANTASY_PIPELINE SERVICE NOT AVAILABLE")
        raise HTTPException(
            status_code=503, detail="Fantasy pipeline service unavailable"
        )

    try:
        fantasy_service = get_service("fantasy_pipeline")
        logger.info(
            f"🔍 CALLING get_league_roster with league_id={league_id}, user_id={current_user['user_id']}"
        )
        roster = await fantasy_service.get_league_roster(
            league_id, current_user.get("id") or current_user.get("user_id")
        )
        logger.info(f"🔍 ROSTER RETRIEVED: {len(roster)} players")

        if not roster:
            logger.error(
                f"🚨 NO ROSTER DATA FOUND for league {league_id}, user {current_user['user_id']}"
            )
            raise HTTPException(
                status_code=404, detail="No roster data found for this league and user"
            )

        return {"status": "success", "roster": roster}
    except Exception as e:
        logger.error(f"🚨 ERROR fetching roster for league {league_id}: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch roster: {str(e)}")


@app.get("/api/fantasy/projections")
async def get_fantasy_projections(current_user: dict = Depends(get_current_user)):
    """Get fantasy projections - REAL DATA ONLY"""
    logger.info(f"🔍 PROJECTIONS CALLED - User: {current_user['user_id']}")

    service_available = is_service_available("fantasy_pipeline")
    logger.info(f"🔍 FANTASY_PIPELINE SERVICE AVAILABLE: {service_available}")

    if not service_available:
        logger.error("🚨 FANTASY_PIPELINE SERVICE NOT AVAILABLE")
        raise HTTPException(
            status_code=503, detail="Fantasy pipeline service unavailable"
        )

    try:
        fantasy_service = get_service("fantasy_pipeline")

        # Get real NFL players and generate projections
        players = await fantasy_service.get_nfl_players(limit=50)

        if not players:
            logger.error("🚨 NO PLAYER DATA AVAILABLE")
            raise HTTPException(status_code=404, detail="No player data available")

        # Get mock games data for projections (this would normally come from a games service)
        mock_games = [
            {"home_team": "BUF", "away_team": "MIA"},
            {"home_team": "SF", "away_team": "LAR"},
            {"home_team": "PHI", "away_team": "DAL"},
        ]

        projections = fantasy_service.generate_fantasy_projections(players, mock_games)

        logger.info(f"🔍 GENERATED {len(projections)} PROJECTIONS")

        return {"status": "success", "projections": projections}

    except Exception as e:
        logger.error(f"🚨 ERROR fetching fantasy projections: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch projections: {str(e)}"
        )


@app.options("/api/fantasy/disconnect/{fantasy_user_id}")
async def options_disconnect_fantasy_account():
    """Handle CORS preflight for fantasy account disconnect"""
    return {}


@app.delete("/api/fantasy/disconnect/{fantasy_user_id}")
async def disconnect_fantasy_account(
    fantasy_user_id: str, current_user: dict = Depends(get_current_user)
):
    """Disconnect a fantasy sports account"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service

        result = await fantasy_connection_service.disconnect_platform(
            user_id=current_user.get("id") or current_user.get("user_id"),
            platform_user_id=fantasy_user_id,
        )
        return result
    except Exception as e:
        logger.error(
            f"Error disconnecting fantasy account {fantasy_user_id} for user {current_user['user_id']}: {e}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to disconnect fantasy account"
        )


@app.get("/api/v1/fantasy/standings/{league_id}")
async def get_fantasy_standings(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Get fantasy league standings"""
    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get league teams (which includes standings data)
        teams = await sleeper_service.get_league_teams(league_id)

        # Sort teams by wins, then points for
        standings = sorted(
            teams,
            key=lambda x: (x.get("wins", 0), x.get("points_for", 0)),
            reverse=True,
        )

        # Add ranking
        for i, team in enumerate(standings):
            team["rank"] = i + 1

        return {
            "status": "success",
            "standings": standings,
            "message": f"Retrieved standings for {len(standings)} teams",
        }
    except Exception as e:
        logger.error(f"Error getting standings for league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get fantasy standings")


@app.get("/api/fantasy/players/search")
async def search_fantasy_players(
    q: str = None, current_user: dict = Depends(get_current_user)
):
    """Search for fantasy players"""
    try:
        if not q or len(q.strip()) < 2:
            return {
                "status": "success",
                "players": [],
                "message": "Please enter at least 2 characters to search",
            }

        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get all players and filter by search query
        all_players = await sleeper_service._get_all_players()

        search_query = q.lower().strip()
        matching_players = []

        # Search through players for name matches
        for player_id, player_data in all_players.items():
            if not player_data:
                continue

            # Check if search query matches first name, last name, or full name
            first_name = (player_data.get("first_name") or "").lower()
            last_name = (player_data.get("last_name") or "").lower()
            full_name = f"{first_name} {last_name}".strip()

            if (
                search_query in first_name
                or search_query in last_name
                or search_query in full_name
            ):

                # Format player data for frontend
                formatted_player = {
                    "player_id": player_id,
                    "name": (
                        full_name.title()
                        if full_name
                        else player_data.get("full_name", "Unknown")
                    ),
                    "first_name": player_data.get("first_name", ""),
                    "last_name": player_data.get("last_name", ""),
                    "position": player_data.get("position", "N/A"),
                    "team": player_data.get("team", "N/A"),
                    "age": player_data.get("age"),
                    "years_exp": player_data.get("years_exp"),
                    "fantasy_positions": player_data.get("fantasy_positions", []),
                    "status": player_data.get("status", ""),
                    "injury_status": player_data.get("injury_status"),
                }
                matching_players.append(formatted_player)

        # Sort by relevance (exact matches first, then partial matches)
        matching_players.sort(
            key=lambda x: (
                search_query != x["name"].lower(),  # Exact matches first
                x["name"].lower().find(search_query),  # Then by position in name
            )
        )

        # Limit to top 50 results for performance
        matching_players = matching_players[:50]

        return {
            "status": "success",
            "players": matching_players,
            "message": f"Found {len(matching_players)} players matching '{q}'",
        }

    except Exception as e:
        logger.error(f"Error searching players with query '{q}': {e}")
        raise HTTPException(status_code=500, detail="Failed to search fantasy players")


@app.get("/api/fantasy/recommendations/start-sit/{week}")
async def get_start_sit_recommendations(
    week: int, current_user: dict = Depends(get_current_user), db=Depends(get_db)
):
    """Get start/sit recommendations for a given week based on user's actual roster"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service
        from app.services.sleeper_fantasy_service import SleeperFantasyService
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        sleeper_service = SleeperFantasyService()
        analytics_service = PlayerAnalyticsService(db)

        def calculate_confidence(game_points, total_games, position):
            """Calculate confidence based on data quality, consistency, and sample size"""
            if not game_points:
                return 50

            # Base confidence starts with sample size
            if len(game_points) >= 3:
                base_confidence = 85
            elif len(game_points) == 2:
                base_confidence = 75
            else:
                base_confidence = 65

            # Adjust for consistency (lower variance = higher confidence)
            if len(game_points) > 1:
                import statistics

                mean_points = statistics.mean(game_points)
                if mean_points > 0:
                    variance = statistics.stdev(game_points)
                    consistency_factor = max(0, 1 - (variance / mean_points))
                    consistency_adjustment = consistency_factor * 10  # Up to +10 points
                else:
                    consistency_adjustment = -10  # Penalize zero averages
            else:
                consistency_adjustment = 0

            # Adjust for total sample size (more games = higher confidence)
            sample_size_bonus = min(5, total_games - 3)  # Up to +5 for 8+ games

            # Position-specific adjustments
            position_modifiers = {
                "QB": 5,  # QBs are more predictable
                "K": 0,  # Kickers are less predictable
                "DEF": -5,  # Defenses are least predictable
                "RB": 2,  # RBs moderately predictable
                "WR": 0,  # WRs baseline
                "TE": -2,  # TEs slightly less predictable
            }
            position_adjustment = position_modifiers.get(position, 0)

            # Calculate final confidence
            final_confidence = (
                base_confidence
                + consistency_adjustment
                + sample_size_bonus
                + position_adjustment
            )

            # Clamp between 35% and 95%
            return int(max(35, min(95, final_confidence)))

        # Get user's connected leagues
        user_leagues = await fantasy_connection_service.get_user_leagues(
            current_user.get("id") or current_user.get("user_id")
        )

        if not user_leagues.get("leagues"):
            return {
                "status": "success",
                "recommendations": [],
                "message": "No connected fantasy leagues found",
            }

        recommendations = []

        # Process each league
        for league in user_leagues["leagues"][:1]:  # Focus on first league for now
            try:
                league_id = league.get("league_id") or league.get("id")
                logger.info(
                    f"Processing league: {league_id}, name: {league.get('name')}"
                )
                if not league_id:
                    logger.warning("No league_id found, skipping league")
                    continue

                # Get league standings to find user's team
                league_standings = await sleeper_service.get_league_standings(league_id)
                logger.info(f"League standings: {len(league_standings)} teams")
                user_team = None

                # Find user's team by matching owner info
                for team in league_standings:
                    logger.info(
                        f"Checking team: {team.get('name')} - Owner: {team.get('owner_name')}"
                    )
                    # Try to match by owner name or other identifiers
                    if (
                        team.get("owner_name")
                        and "byetz" in team.get("owner_name", "").lower()
                    ):
                        user_team = team
                        logger.info(f"Found user team by name match: {user_team}")
                        break

                if not user_team:
                    # If we can't find by name, take the first team as fallback
                    if league_standings:
                        user_team = league_standings[0]
                        logger.info(
                            f"Using first team as fallback: {user_team.get('name')}"
                        )

                if not user_team:
                    logger.warning("No user team found")
                    continue

                # Get user's roster using owner_id
                owner_id = user_team.get("owner_id")
                logger.info(f"Getting roster for owner_id: {owner_id}")
                team_roster_ids = await sleeper_service.get_roster_by_owner(
                    league_id, owner_id
                )
                logger.info(f"Team roster player IDs: {team_roster_ids}")

                if not team_roster_ids:
                    logger.warning("No team roster found")
                    continue

                # Get player details for each roster player
                sleeper_players = await sleeper_service._get_all_players()
                team_roster = []
                for player_id in team_roster_ids:
                    if player_id in sleeper_players:
                        player_data = sleeper_players[player_id]
                        team_roster.append(
                            {
                                "player_id": player_id,
                                "name": f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
                                "position": player_data.get("position"),
                                "team": player_data.get("team"),
                                "fantasy_positions": player_data.get(
                                    "fantasy_positions", []
                                ),
                                "injury_status": player_data.get("injury_status"),
                                "status": player_data.get("status"),
                            }
                        )

                logger.info(f"Processed team roster: {len(team_roster)} players")

                if not team_roster:
                    logger.warning("No team roster found")
                    continue

                # Get league roster rules for proper START/SIT decisions
                from app.services.sleeper_fantasy_service import SleeperFantasyService

                sleeper_service_temp = SleeperFantasyService()
                league_details = await sleeper_service_temp.get_league_details(
                    league_id
                )
                roster_positions = league_details.get("roster_positions", [])
                starting_positions = [
                    pos for pos in roster_positions if pos not in ["BN", "IR"]
                ]

                # Count required starting positions
                position_requirements = {}
                for pos in starting_positions:
                    position_requirements[pos] = position_requirements.get(pos, 0) + 1

                logger.info(f"League roster requirements: {position_requirements}")

                # Analyze each player on the roster - first pass: calculate projections
                logger.info(f"Processing {len(team_roster)} players on roster")
                player_projections = []

                for i, player in enumerate(team_roster[:15]):  # Limit to 15 players
                    try:
                        sleeper_player_id = player.get("player_id")
                        logger.info(
                            f"Processing player {i+1}: {player.get('name')} ({sleeper_player_id})"
                        )
                        if not sleeper_player_id:
                            logger.warning(f"No player_id for player: {player}")
                            continue

                        # Map Sleeper player ID to fantasy_players.id for analytics lookup
                        analytics = None
                        try:
                            # Query database for the mapping
                            fantasy_player_query = db.execute(
                                text(
                                    "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
                                ),
                                {"sleeper_id": str(sleeper_player_id)},
                            )
                            fantasy_player_row = fantasy_player_query.fetchone()

                            if fantasy_player_row:
                                fantasy_player_id = fantasy_player_row[0]
                                logger.info(
                                    f"Mapped Sleeper ID {sleeper_player_id} to fantasy_players.id {fantasy_player_id}"
                                )

                                # Now get analytics using the correct ID
                                analytics = (
                                    await analytics_service.get_player_analytics(
                                        fantasy_player_id, season=2024
                                    )
                                )
                                logger.info(
                                    f"Analytics result for {player.get('name')}: {len(analytics) if analytics else 0} records"
                                )
                            else:
                                logger.warning(
                                    f"No fantasy_players mapping found for Sleeper ID {sleeper_player_id}"
                                )
                        except Exception as e:
                            logger.warning(
                                f"Error mapping/fetching analytics for player {sleeper_player_id}: {e}"
                            )
                            analytics = None

                        # Calculate projected points based on recent performance
                        projected_points = 0.0
                        confidence = 75  # Base confidence

                        if analytics and len(analytics) > 0:
                            # Use average of last 3 games
                            recent_games = analytics[:3]
                            game_points = [
                                game.get("ppr_points", 0) for game in recent_games
                            ]
                            total_points = sum(game_points)
                            projected_points = (
                                total_points / len(recent_games)
                                if recent_games
                                else 0.0
                            )

                            # Calculate confidence based on data quality and consistency
                            position = player.get("position", "")
                            confidence = calculate_confidence(
                                game_points, len(analytics), position
                            )
                            logger.info(
                                f"Player {player.get('name')} analytics: {len(analytics)} games, projected: {projected_points:.1f}, confidence: {confidence}%"
                            )
                        else:
                            # Fallback projection based on position
                            position_projections = {
                                "QB": 24.5,
                                "RB": 15.2,
                                "WR": 13.8,
                                "TE": 9.5,
                                "K": 8.2,
                                "DEF": 7.8,
                            }
                            projected_points = position_projections.get(
                                player.get("position", ""), 8.0
                            )
                            confidence = 50  # Lower confidence for projections without recent data
                            logger.info(
                                f"Player {player.get('name')} using fallback projection: {projected_points}, confidence: {confidence}%"
                            )

                        # Store player projection data for later START/SIT assignment
                        position = player.get("position", "BENCH")

                        # Check injury status
                        injury_status = player.get("injury_status")
                        status = player.get("status")
                        is_injured = injury_status in [
                            "Out",
                            "IR",
                            "PUP",
                            "Suspended",
                        ] or status in ["Inactive", "Injured Reserve"]

                        # Adjust confidence and reason if injured
                        if is_injured:
                            confidence = 10  # Very low confidence for injured players
                            injury_reason = f" (INJURED: {injury_status or status})"
                        else:
                            injury_reason = ""

                        player_data = {
                            "player_id": sleeper_player_id,
                            "player_name": player.get("name", "Unknown Player"),
                            "name": player.get("name", "Unknown Player"),
                            "position": position,
                            "team": player.get("team", "N/A"),
                            "confidence": confidence,
                            "projected_points": round(projected_points, 1),
                            "has_analytics": analytics is not None
                            and len(analytics) > 0,
                            "injury_status": injury_status,
                            "status": status,
                            "is_injured": is_injured,
                            "reason": (
                                f"Based on recent performance averaging {projected_points:.1f} pts{injury_reason}"
                                if analytics
                                else f"Projected {projected_points:.1f} pts (no recent data){injury_reason}"
                            ),
                            "league_name": league.get("name", "Unknown League"),
                            "league_context": {
                                "league_id": league_id,
                                "league_name": league.get("name", "Unknown League"),
                                "team_name": user_team.get("name", "Your Team"),
                            },
                        }
                        player_projections.append(player_data)
                        logger.info(
                            f"Added projection for {player.get('name')}: {projected_points:.1f} pts, injury_status: {injury_status}, status: {status}, is_injured: {is_injured}"
                        )

                    except Exception as player_error:
                        logger.warning(
                            f"Failed to analyze player {player.get('player_id')}: {player_error}"
                        )
                        continue

                # Second pass: Assign START/SIT based on projected points and roster requirements
                logger.info(
                    f"Assigning START/SIT for {len(player_projections)} players"
                )

                # Sort players by position and projected points (highest first)
                players_by_position = {}
                for player in player_projections:
                    pos = player["position"]
                    if pos not in players_by_position:
                        players_by_position[pos] = []
                    players_by_position[pos].append(player)

                # Sort each position by health first, then projected points (descending)
                for pos in players_by_position:
                    players_by_position[pos].sort(
                        key=lambda x: (x["is_injured"], -x["projected_points"])
                    )

                # Assign START/SIT based on roster requirements
                for pos, players in players_by_position.items():
                    required_starters = position_requirements.get(pos, 0)
                    logger.info(
                        f"Position {pos}: {len(players)} players, {required_starters} starters required"
                    )

                    for i, player in enumerate(players):
                        rank_in_position = i + 1
                        is_starter = rank_in_position <= required_starters

                        # Create recommendation
                        recommendation = {
                            **player,  # Include all player data
                            "recommendation": "START" if is_starter else "SIT",
                            "rank_in_position": rank_in_position,
                            "total_in_position": len(players),
                        }
                        recommendations.append(recommendation)
                        logger.info(
                            f"{player['player_name']} ({pos}): {player['projected_points']} pts, rank #{rank_in_position}, {'START' if is_starter else 'SIT'}"
                        )

                # Handle FLEX positions (RB/WR/TE can fill FLEX spots)
                flex_positions = position_requirements.get("FLEX", 0)
                if flex_positions > 0:
                    logger.info(f"Processing {flex_positions} FLEX positions")

                    # Get all RB/WR/TE players who are currently marked as SIT
                    flex_eligible = [
                        r
                        for r in recommendations
                        if r["position"] in ["RB", "WR", "TE"]
                        and r["recommendation"] == "SIT"
                    ]

                    # Sort by health first, then projected points (highest first)
                    flex_eligible.sort(
                        key=lambda x: (x["is_injured"], -x["projected_points"])
                    )

                    # Promote top FLEX-eligible players to START
                    for i in range(min(flex_positions, len(flex_eligible))):
                        flex_eligible[i]["recommendation"] = "START"
                        logger.info(
                            f"FLEX promotion: {flex_eligible[i]['player_name']} -> START"
                        )

            except Exception as league_error:
                logger.warning(
                    f"Failed to get recommendations for league {league.get('league_id')}: {league_error}"
                )
                continue

        # Sort recommendations: START players first, then by projected points
        recommendations.sort(
            key=lambda x: (x["recommendation"] != "START", -x["projected_points"])
        )

        return {
            "status": "success",
            "recommendations": recommendations,
            "message": f"Generated {len(recommendations)} start/sit recommendations for week {week} based on your roster",
        }
    except Exception as e:
        logger.error(f"Error getting start/sit recommendations for week {week}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get start/sit recommendations"
        )


@app.get("/api/fantasy/recommendations/waiver-wire/{week}")
async def get_waiver_wire_recommendations(
    week: int, current_user: dict = Depends(get_current_user)
):
    """Get waiver wire recommendations for a given week"""
    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get trending players being added
        trending_adds = await sleeper_service.get_trending_players("add")

        # Get trending players being dropped for additional context
        trending_drops = await sleeper_service.get_trending_players("drop")

        # Format recommendations with both adds and drops
        recommendations = []

        # Add top trending additions
        for player in trending_adds[:10]:  # Top 10 trending adds
            trend_count = player.get("trend_count", 0)
            # Calculate priority score based on trend count (normalize to 0-10 scale)
            priority_score = min(10.0, max(1.0, trend_count / 10000))
            is_high_priority = trend_count > 50000
            faab_percentage = min(20, max(3, int(trend_count / 10000)))

            recommendations.append(
                {
                    **player,
                    "recommendation_type": "add",
                    "priority": "high" if is_high_priority else "medium",
                    "priority_score": round(priority_score, 1),
                    "trend_count": trend_count,
                    "waiver_suggestion": {
                        "suggestion_type": "FAAB",
                        "faab_percentage": faab_percentage,
                        "claim_advice": (
                            f"Top waiver priority"
                            if is_high_priority
                            else "Medium priority"
                        ),
                    },
                    "suggested_fab_percentage": faab_percentage,
                }
            )

        # Add context about trending drops
        for player in trending_drops[:5]:  # Top 5 trending drops
            recommendations.append(
                {
                    **player,
                    "recommendation_type": "drop",
                    "priority": "low",
                    "priority_score": 1.0,
                    "trend_count": player.get("trend_count", 0),
                    "waiver_suggestion": {
                        "suggestion_type": "DROP",
                        "claim_advice": "Consider dropping",
                    },
                    "suggested_fab_percentage": 0,
                }
            )

        return {
            "status": "success",
            "recommendations": recommendations,
            "message": f"Retrieved {len(recommendations)} waiver wire recommendations for week {week}",
        }
    except Exception as e:
        logger.error(f"Error getting waiver wire recommendations for week {week}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get waiver wire recommendations"
        )


@app.get("/api/fantasy/leagues/{league_id}/rules")
async def get_league_rules(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Get fantasy league rules and settings"""
    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get detailed league information
        league_details = await sleeper_service.get_league_details(league_id)

        # Get the actual roster count from teams data
        teams_count = len(league_details.get("teams", []))

        # If teams count is 0, try to get it from the raw league data
        if teams_count == 0:
            # Make a direct API call to get league info
            import httpx

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(
                        f"https://api.sleeper.app/v1/league/{league_id}"
                    )
                    if response.status_code == 200:
                        raw_league_data = response.json()
                        teams_count = raw_league_data.get("total_rosters", 0)
                        # Update league_details with missing data
                        league_details.update(raw_league_data)
                except Exception as e:
                    logger.warning(f"Could not fetch additional league data: {e}")

        # Get the raw scoring settings from Sleeper
        raw_scoring = league_details.get("scoring_settings", {})

        # Structure the scoring settings to match frontend expectations
        structured_scoring = {
            "passing": {
                "touchdowns": raw_scoring.get("pass_td", 6),
                "yards_per_point": (
                    1.0 / raw_scoring.get("pass_yd", 25)
                    if raw_scoring.get("pass_yd", 0) > 0
                    else 0
                ),
                "interceptions": raw_scoring.get("pass_int", -2),
            },
            "rushing": {
                "touchdowns": raw_scoring.get("rush_td", 6),
                "yards_per_point": (
                    1.0 / raw_scoring.get("rush_yd", 10)
                    if raw_scoring.get("rush_yd", 0) > 0
                    else 0
                ),
                "fumbles": raw_scoring.get("fum_lost", -2),
            },
            "receiving": {
                "touchdowns": raw_scoring.get("rec_td", 6),
                "yards_per_point": (
                    1.0 / raw_scoring.get("rec_yd", 10)
                    if raw_scoring.get("rec_yd", 0) > 0
                    else 0
                ),
                "receptions": raw_scoring.get("rec", 1),
                "fumbles": raw_scoring.get("fum_lost", -2),
            },
            "kicking": {
                "field_goals": raw_scoring.get("fgm", 3),
                "extra_points": raw_scoring.get("xpm", 1),
                "field_goal_misses": raw_scoring.get("fgmiss", 0),
            },
            "defense": {
                "sacks": raw_scoring.get("sack", 1),
                "interceptions": raw_scoring.get("def_int", 2),
                "fumble_recoveries": raw_scoring.get("fum_rec", 2),
                "touchdowns": raw_scoring.get("def_td", 6),
            },
            "special_scoring": [],  # Add empty special scoring to prevent frontend error
        }

        # Get roster positions and calculate roster info
        roster_positions = league_details.get("roster_positions", [])
        starting_positions = [
            pos for pos in roster_positions if pos not in ["BN", "IR"]
        ]
        bench_positions = [pos for pos in roster_positions if pos in ["BN", "IR"]]

        # Use the calculated teams count
        total_rosters = teams_count
        league_type = (
            f"{total_rosters}-Team League" if total_rosters > 0 else "Standard League"
        )

        # Count position requirements
        position_counts = {}
        for pos in starting_positions:
            position_counts[pos] = position_counts.get(pos, 0) + 1

        # Build position requirements text
        position_requirements = []
        for pos, count in position_counts.items():
            if count > 1:
                position_requirements.append(f"{count} {pos}")
            else:
                position_requirements.append(pos)

        # Extract rules and settings from league details
        rules = {
            "league_name": league_details.get("name", "Unknown League"),
            "league_type": league_type,
            "total_rosters": total_rosters,
            "teams_count": total_rosters,
            "platform": "Sleeper",
            "scoring_type": structured_scoring.get("receiving", {}).get("receptions", 0)
            > 0
            and "PPR"
            or "Standard",
            "roster_positions": roster_positions,
            "scoring_settings": structured_scoring,
            "waiver_settings": {
                "waiver_type": league_details.get("waiver_type", "waiver_priority"),
                "waiver_budget": league_details.get("waiver_budget", 100),
                "waiver_clear_days": league_details.get("waiver_clear_days", 1),
                **league_details.get("waiver_settings", {}),
            },
            "playoff_settings": {
                "playoff_week_start": league_details.get("playoff_week_start", 15),
                "playoff_teams": league_details.get("playoff_teams", 4),
                "playoff_rounds": league_details.get("playoff_rounds", 2),
            },
            "draft_settings": {
                "draft_type": league_details.get("draft_type", "snake"),
                "draft_order": league_details.get("draft_order"),
                "draft_rounds": league_details.get(
                    "draft_rounds", len(roster_positions)
                ),
            },
            "roster_config": {
                "total_spots": len(roster_positions),
                "starting_spots": len(starting_positions),
                "bench_spots": len(bench_positions),
                "starting_lineup": starting_positions,
                "bench_lineup": bench_positions,
            },
            "position_requirements": position_requirements,
            "league_features": {
                "trade_deadline": league_details.get("trade_deadline"),
                "taxi_slots": league_details.get("taxi_slots", 0),
                "reserve_slots": league_details.get("reserve_slots", 0),
                "waiver_type": league_details.get("waiver_type", "waiver_priority"),
                "daily_waivers": league_details.get("daily_waivers", False),
            },
            "season": league_details.get("season", "2024"),
            "status": league_details.get("status", "pre_draft"),
        }

        return {
            "status": "success",
            "rules": rules,
            "message": f"Retrieved rules for league {league_details.get('name', league_id)}",
        }
    except Exception as e:
        logger.error(f"Error getting rules for league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get league rules")


@app.delete("/api/fantasy/leagues/{league_id}")
async def delete_fantasy_league(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Delete/leave a fantasy league"""
    try:
        return {
            "status": "success",
            "message": "Fantasy league deletion endpoint - implementation in progress",
        }
    except Exception as e:
        logger.error(f"Error deleting league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete fantasy league")


# Odds and Markets API Endpoints
@app.options("/api/odds/americanfootball_nfl")
async def options_nfl_odds():
    """Handle CORS preflight for NFL odds"""
    return {}


@app.get("/api/odds/americanfootball_nfl")
async def get_nfl_odds():
    """Get NFL odds directly"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import OddsAPIService

            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("americanfootball_nfl")

                # Store games in database for parlay creation
                stored_count = await _store_games_in_database(
                    games, "americanfootball_nfl"
                )
                logger.info(
                    f"NFL: Fetched {len(games)} games, stored {stored_count} in database"
                )

                return {"status": "success", "games": games}
        except Exception as e:
            logger.error(f"Error fetching NFL odds: {e}")

    # Return error if API key not configured
    return {
        "status": "error",
        "games": [],
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real NFL odds.",
    }


@app.options("/api/odds/basketball_nba")
async def options_nba_odds():
    """Handle CORS preflight for NBA odds"""
    return {}


@app.get("/api/odds/basketball_nba")
async def get_nba_odds():
    """Get NBA odds directly"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import OddsAPIService

            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("basketball_nba")

                # Store games in database for parlay creation
                stored_count = await _store_games_in_database(games, "basketball_nba")
                logger.info(
                    f"NBA: Fetched {len(games)} games, stored {stored_count} in database"
                )

                return {"status": "success", "games": games}
        except Exception as e:
            logger.error(f"Error fetching NBA odds: {e}")

    return {
        "status": "error",
        "games": [],
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real NBA odds.",
    }


@app.options("/api/odds/baseball_mlb")
async def options_mlb_odds():
    """Handle CORS preflight for MLB odds"""
    return {}


@app.get("/api/odds/baseball_mlb")
async def get_mlb_odds():
    """Get MLB odds directly"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import OddsAPIService

            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("baseball_mlb")

                # Store games in database for parlay creation
                stored_count = await _store_games_in_database(games, "baseball_mlb")
                logger.info(
                    f"MLB: Fetched {len(games)} games, stored {stored_count} in database"
                )

                return {"status": "success", "games": games}
        except Exception as e:
            logger.error(f"Error fetching MLB odds: {e}")

    return {
        "status": "error",
        "games": [],
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real MLB odds.",
    }


@app.options("/api/odds/icehockey_nhl")
async def options_nhl_odds():
    """Handle CORS preflight for NHL odds"""
    return {}


@app.get("/api/odds/icehockey_nhl")
async def get_nhl_odds():
    """Get NHL (Ice Hockey) odds"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import OddsAPIService

            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("icehockey_nhl")

                # Store games in database for parlay creation
                stored_count = await _store_games_in_database(games, "icehockey_nhl")
                logger.info(
                    f"NHL: Fetched {len(games)} games, stored {stored_count} in database"
                )

                return {"status": "success", "games": games}
        except Exception as e:
            logger.error(f"Error fetching NHL odds: {e}")

    return {
        "status": "error",
        "games": [],
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real NHL odds.",
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


@app.options("/api/odds/americanfootball_ncaaf")
async def options_ncaaf_odds():
    """Handle CORS preflight for NCAAF odds"""
    return {}


@app.get("/api/odds/americanfootball_ncaaf")
async def get_ncaaf_odds():
    """Get NCAAF (College Football) odds"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import OddsAPIService

            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("americanfootball_ncaaf")

                # Store games in database for parlay creation
                stored_count = await _store_games_in_database(
                    games, "americanfootball_ncaaf"
                )
                logger.info(
                    f"NCAAF: Fetched {len(games)} games, stored {stored_count} in database"
                )

                return {"status": "success", "games": games}
        except Exception as e:
            logger.error(f"Error fetching NCAAF odds: {e}")

    return {
        "status": "error",
        "games": [],
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real NCAAF odds.",
    }


@app.get("/api/odds/nfl")
async def get_nfl_odds_legacy():
    """Get NFL odds (legacy endpoint)"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import OddsAPIService

            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                games = await service.get_odds("americanfootball_nfl")
                return {"status": "success", "odds": games}
        except Exception as e:
            logger.error(f"Error fetching NFL odds: {e}")

    return {
        "status": "error",
        "odds": [],
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real NFL odds.",
    }


@app.get("/api/odds/popular")
async def get_popular_sports_odds():
    """Get odds for popular sports (NFL, NBA, MLB, NHL)"""
    if settings.ODDS_API_KEY:
        try:
            from app.services.odds_api_service import get_popular_sports_odds

            games = await get_popular_sports_odds()
            return {"status": "success", "games": games, "count": len(games)}
        except Exception as e:
            logger.error(f"Error fetching popular sports odds: {e}")
            # If real API fails, return empty games list instead of mock data
            return {
                "status": "error",
                "games": [],
                "count": 0,
                "message": f"Failed to fetch odds: {str(e)}",
            }

    # Return error if API key is not configured
    return {
        "status": "error",
        "games": [],
        "count": 0,
        "message": "ODDS_API_KEY not configured. Please set your API key to fetch real odds data.",
    }


# === PLAYER PROPS ENDPOINTS ===


@app.get("/api/player-props/{sport}/{event_id}")
async def get_player_props(
    sport: str,
    event_id: str,
    markets: Optional[str] = None,
):
    """
    Get player props for a specific event

    Args:
        sport: Sport key (e.g., 'americanfootball_nfl', 'basketball_nba')
        event_id: The odds API event ID
        markets: Optional comma-separated list of specific markets to fetch

    Returns:
        Player props organized by market with FanDuel odds
    """
    if not settings.ODDS_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="ODDS_API_KEY not configured. Please set your API key.",
        )

    # Validate sport supports player props
    supported_sports = [
        "americanfootball_nfl",
        "basketball_nba",
        "icehockey_nhl",
        "baseball_mlb",
    ]
    if sport not in supported_sports:
        raise HTTPException(
            status_code=400,
            detail=f"Sport {sport} not supported for player props. Supported: {', '.join(supported_sports)}",
        )

    try:
        from app.services.odds_api_service import OddsAPIService
        from app.services.player_props_service import PlayerPropsService

        async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
            props_service = PlayerPropsService(odds_service)

            # Parse markets if provided
            markets_list = markets.split(",") if markets else None

            props_data = await props_service.get_player_props_for_event(
                sport=sport,
                event_id=event_id,
                markets=markets_list,
            )

            if "error" in props_data:
                raise HTTPException(status_code=404, detail=props_data["error"])

            return {
                "status": "success",
                "data": props_data,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching player props for {sport} event {event_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/player-props/markets/{sport}")
async def get_available_markets(sport: str):
    """
    Get list of available player prop markets for a sport

    Args:
        sport: Sport key (e.g., 'americanfootball_nfl')

    Returns:
        List of available market keys with display names
    """
    try:
        from app.services.player_props_service import (
            PlayerPropsService,
            PLAYER_PROP_MARKETS,
        )

        # Get available markets for sport
        markets = PLAYER_PROP_MARKETS.get(sport, [])

        if not markets:
            raise HTTPException(
                status_code=404,
                detail=f"No player prop markets available for sport: {sport}",
            )

        # Create props service instance to get display names
        from app.services.odds_api_service import OddsAPIService

        async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
            props_service = PlayerPropsService(odds_service)

            markets_with_names = [
                {
                    "key": market,
                    "display_name": props_service.get_market_display_name(market),
                }
                for market in markets
            ]

        return {
            "status": "success",
            "sport": sport,
            "markets": markets_with_names,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching markets for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/popular-games")
async def get_popular_games(sport: Optional[str] = None, db: Session = Depends(get_db)):
    """Get popular games from database (cached by scheduled sync)"""
    try:
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        from app.models.database_models import Game

        # Work in Eastern Time since that's where most US sports are scheduled
        eastern = ZoneInfo("America/New_York")
        now_et = datetime.now(eastern)

        # Get "today" in Eastern Time - from 6 hours ago through end of day
        today_start_et = now_et - timedelta(hours=6)
        today_end_et = now_et.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert to UTC for database filtering
        today_start = today_start_et.astimezone(timezone.utc)
        today_end = today_end_et.astimezone(timezone.utc)

        logger.info(
            f"Fetching popular games for today in ET: {now_et.strftime('%Y-%m-%d %H:%M %Z')}"
        )
        logger.info(f"Date range (UTC): {today_start} to {today_end}")

        # Query database for games happening today
        # NOTE: Showing all games until broadcast heuristics are tuned
        games_query = (
            db.query(Game)
            .filter(
                Game.commence_time >= today_start,
                Game.commence_time <= today_end,
            )
            .order_by(Game.commence_time)
            .all()
        )

        logger.info(f"Found {len(games_query)} games in database for today")

        # Group by sport
        games_by_sport = {"nfl": [], "nba": [], "mlb": [], "nhl": []}

        # Map sport keys to friendly names
        sport_map = {
            "americanfootball_nfl": "nfl",
            "americanfootball_ncaaf": "nfl",
            "baseball_mlb": "mlb",
            "basketball_nba": "nba",
            "basketball_ncaab": "nba",
            "basketball_wnba": "nba",
            "icehockey_nhl": "nhl",
            "soccer_epl": "soccer",
            "soccer_mls": "soccer",
        }

        # Process games from database
        for game in games_query:
            friendly_sport = sport_map.get(game.sport_key, game.sport_key)

            # Only include sports we're tracking
            if friendly_sport not in games_by_sport:
                continue

            # Skip games without broadcast info
            if not game.broadcast_info:
                continue

            # Extract bookmakers odds from odds_data JSON
            bookmakers_odds = []
            if game.odds_data and isinstance(game.odds_data, list):
                # Return bookmakers (currently FanDuel only to conserve API tokens)
                bookmakers_odds = game.odds_data

            # Ensure UTC timezone is included in ISO format
            commence_time_iso = game.commence_time.isoformat()
            if game.commence_time.tzinfo is None:
                # Add UTC timezone if missing
                from datetime import timezone as tz

                commence_time_iso = game.commence_time.replace(
                    tzinfo=tz.utc
                ).isoformat()

            # Create game dict with all necessary fields
            game_dict = {
                "id": game.id,
                "sport": friendly_sport,
                "sport_key": game.sport_key,
                "sport_title": game.sport_title,
                "home_team": game.home_team,
                "away_team": game.away_team,
                "commence_time": commence_time_iso,  # ISO format with timezone
                "bookmakers": bookmakers_odds,  # Include all bookmakers
                "broadcast": game.broadcast_info,  # Include broadcast info
            }

            logger.debug(
                f"Adding game {game.id} to {friendly_sport}: {game.home_team} vs {game.away_team}"
            )
            games_by_sport[friendly_sport].append(game_dict)

        # Limit to 10 games per sport
        for sport_key in games_by_sport:
            games_by_sport[sport_key] = games_by_sport[sport_key][:10]

        # Log final counts
        sport_counts = {k: len(v) for k, v in games_by_sport.items() if v}
        logger.info(f"Popular games by sport: {sport_counts}")

        # Return specific sport or all sports
        if sport:
            sport_games = games_by_sport.get(sport.lower(), [])
            return {
                "status": "success",
                "popular_games": {sport.lower(): sport_games},
                "total_count": len(sport_games),
                "message": f"Found {len(sport_games)} popular games for {sport.upper()}",
            }
        else:
            total_count = sum(len(games) for games in games_by_sport.values())
            response = {
                "status": "success",
                "popular_games": games_by_sport,
                "total_count": total_count,
                "message": f"Found {total_count} popular games across all sports",
            }

            # Add debug info
            response["debug"] = {
                "total_in_db": len(games_query),
                "date_range_utc": {
                    "start": today_start.isoformat(),
                    "end": today_end.isoformat(),
                },
                "current_time_et": now_et.isoformat(),
                "sport_counts": {k: len(v) for k, v in games_by_sport.items()},
                "data_source": "database_cache",
            }

            return response

    except Exception as e:
        logger.error(f"Error fetching popular games: {e}")
        import traceback

        logger.error(traceback.format_exc())
        # Return basic fallback
        return {
            "status": "success",
            "popular_games": {"nfl": [], "nba": [], "mlb": [], "nhl": []},
            "total_count": 0,
            "message": "No popular games available at this time",
        }


@app.post("/api/v1/sportsbook-link")
async def generate_sportsbook_link(
    request: dict,
):
    """
    Generate a deep link to a sportsbook with bet information.

    Request body:
    {
        "sportsbook": "fanduel",
        "sport_key": "americanfootball_nfl",
        "home_team": "Atlanta Falcons",
        "away_team": "Buffalo Bills",
        "bet_type": "h2h",  // h2h, spreads, totals
        "bet_selection": "Buffalo Bills"  // optional
    }
    """
    try:
        from app.services.sportsbook_links_service import sportsbook_links_service

        # Extract request data
        sportsbook = request.get("sportsbook", "fanduel")
        sport_key = request.get("sport_key", "")
        home_team = request.get("home_team", "")
        away_team = request.get("away_team", "")
        bet_type = request.get("bet_type", "h2h")
        bet_selection = request.get("bet_selection")

        # Generate link
        link_info = sportsbook_links_service.generate_link(
            sportsbook=sportsbook,
            sport_key=sport_key,
            home_team=home_team,
            away_team=away_team,
            bet_type=bet_type,
            bet_selection=bet_selection,
        )

        return {
            "status": "success",
            "link": link_info["url"],
            "sportsbook": link_info["sportsbook"],
            "requires_manual_selection": link_info["requires_manual_selection"],
            "deep_link_supported": link_info["deep_link_supported"],
            "message": f"Link generated for {sportsbook}. {'Deep linking supported - takes you to the game page.' if link_info['deep_link_supported'] else 'Generic link - you may need to find the game manually.'}",
        }

    except Exception as e:
        logger.error(f"Error generating sportsbook link: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate sportsbook link: {str(e)}"
        )


async def _store_games_in_database(games_data: List, sport_key: str) -> int:
    """Store games from Odds API in the database for parlay creation"""
    if not games_data:
        return 0

    stored_count = 0
    db = SessionLocal()
    try:
        from app.models.database_models import Game, GameStatus

        for game_data in games_data:
            try:
                # Check if game already exists
                existing_game = db.query(Game).filter(Game.id == game_data.id).first()

                if existing_game:
                    # Update existing game with fresh data
                    existing_game.sport_key = game_data.sport_key
                    existing_game.sport_title = game_data.sport_title
                    existing_game.home_team = game_data.home_team
                    existing_game.away_team = game_data.away_team
                    existing_game.commence_time = game_data.commence_time
                    existing_game.last_update = datetime.utcnow()
                    logger.debug(
                        f"Updated game: {game_data.away_team} @ {game_data.home_team}"
                    )
                else:
                    # Create new game
                    new_game = Game(
                        id=game_data.id,
                        sport_key=game_data.sport_key,
                        sport_title=game_data.sport_title,
                        home_team=game_data.home_team,
                        away_team=game_data.away_team,
                        commence_time=game_data.commence_time,
                        status=GameStatus.SCHEDULED,
                        last_update=datetime.utcnow(),
                    )
                    db.add(new_game)
                    logger.debug(
                        f"Created game: {game_data.away_team} @ {game_data.home_team}"
                    )

                stored_count += 1

            except Exception as e:
                logger.error(f"Error storing game {game_data.id}: {e}")
                continue

        db.commit()
        logger.info(f"Stored {stored_count} {sport_key} games in database")

    except Exception as e:
        logger.error(f"Database error storing {sport_key} games: {e}")
        db.rollback()
    finally:
        db.close()

    return stored_count


def _generate_enhanced_popular_games():
    """Return no games for realistic behavior - most days don't have nationally televised games"""

    # For realistic behavior, return empty list since there are typically
    # no nationally televised games on most weekdays
    # In a real implementation, this would integrate with ESPN API or odds API
    # to fetch actual nationally televised games for today

    return []


@app.get("/api/popular-games/{sport}")
async def get_popular_games_by_sport(sport: str):
    """Get popular games for a specific sport"""
    return await get_popular_games(sport=sport)


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
            "markets": ["h2h", "spreads", "totals", "props"],
        },
        {
            "sport": "nba",
            "name": "NBA",
            "markets": ["h2h", "spreads", "totals", "props"],
        },
    ]

    # Add NHL if specifically requested or show all
    if sport == "icehockey_nhl" or not sport:
        markets.append(
            {
                "sport": "icehockey_nhl",
                "name": "NHL",
                "markets": ["h2h", "spreads", "totals"],
            }
        )

    # Filter by sport if specified
    if sport:
        markets = [m for m in markets if m["sport"] == sport]

    return {
        "status": "success",
        "markets": markets,
        "message": "Mock parlay markets - bet service unavailable",
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
                    {"selection": "Lakers -3.5", "odds": -110, "sport": "nba"},
                ],
                "total_odds": 250,
                "popularity_score": 0.85,
            },
            {
                "id": "popular_2",
                "name": "Hockey Hat Trick",
                "legs": [
                    {"selection": "Rangers ML", "odds": -130, "sport": "icehockey_nhl"},
                    {
                        "selection": "Bruins Over 6.5",
                        "odds": -105,
                        "sport": "icehockey_nhl",
                    },
                    {
                        "selection": "McDavid Anytime Goal",
                        "odds": 180,
                        "sport": "icehockey_nhl",
                    },
                ],
                "total_odds": 650,
                "popularity_score": 0.72,
            },
        ],
        "message": "Mock popular parlays - bet service unavailable",
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
            profile = await auth_service.get_user_profile(
                current_user.get("id") or current_user.get("user_id")
            )
            return {
                "status": "success",
                "sports": profile.get("preferred_sports", []),
                "favorite_teams": profile.get("favorite_teams", []),
                "notification_settings": profile.get("notification_settings", {}),
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
            {"sport": "icehockey_nhl", "team": "New York Rangers"},
        ],
        "notification_settings": {
            "game_updates": True,
            "bet_results": True,
            "yetai_predictions": True,
        },
        "message": "Mock sports preferences - auth service unavailable",
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
            status_info = await auth_service.get_user_status(
                current_user.get("id") or current_user.get("user_id")
            )
            return {"status": "success", "profile_status": status_info}
        except Exception as e:
            logger.error(f"Error fetching user profile status: {e}")

    # Mock profile status
    return {
        "status": "success",
        "profile_status": {
            "user_id": current_user.get("id") or current_user.get("user_id"),
            "subscription_tier": current_user.get("subscription_tier", "free"),
            "account_status": "active",
            "profile_completion": 0.85,
            "last_activity": datetime.now(timezone.utc).isoformat(),
            "stats": {"total_bets": 25, "win_rate": 0.68, "favorite_sport": "nfl"},
            "connected_platforms": ["sleeper"],
            "notification_preferences": {"email": True, "push": True},
        },
        "message": "Mock profile status - auth service unavailable",
    }


# Live betting endpoints
@app.options("/api/live-bets/markets")
async def options_live_markets():
    """Handle CORS preflight for live markets"""
    return {}


@app.get("/api/live-bets/markets")
async def get_live_betting_markets(sport: Optional[str] = None):
    """Get available live betting markets with real sports data (public endpoint)"""
    try:
        print(f"Live betting markets endpoint called with sport: {sport}")
        markets = await live_betting_service.get_live_betting_markets(sport)
        print(f"Service returned {len(markets)} markets")

        return {"status": "success", "count": len(markets), "markets": markets}

    except Exception as e:
        print(f"Exception in live betting endpoint: {e}")
        logger.error(f"Error getting live markets: {e}")
        raise HTTPException(status_code=500, detail="Failed to get live markets")


@app.options("/api/live-bets/active")
async def options_active_live_bets():
    """Handle CORS preflight for active live bets"""
    return {}


@app.get("/api/live-bets/active")
async def get_active_live_bets(current_user: dict = Depends(get_current_user)):
    """Get active live bets for the current user"""
    if is_service_available("bet_service"):
        try:
            bet_service = get_service("bet_service")
            active_bets = await bet_service.get_active_live_bets(
                current_user.get("id") or current_user.get("user_id")
            )
            return {"status": "success", "active_bets": active_bets}
        except Exception as e:
            logger.error(f"Error fetching active live bets: {e}")
            return {"status": "error", "error": str(e), "active_bets": []}

    return {
        "status": "error",
        "error": "Bet service is currently unavailable",
        "active_bets": [],
    }


@app.options("/api/live-bets/place")
async def options_place_live_bet():
    """Handle CORS preflight for live bet placement"""
    return {}


@app.post("/api/live-bets/place")
async def place_live_bet(
    bet_request: PlaceLiveBetRequest, current_user: dict = Depends(get_current_user)
):
    """Place a live bet during active game"""
    try:
        result = await simple_unified_bet_service.place_live_bet(
            user_id=current_user.get("id") or current_user.get("user_id"),
            live_bet_data=bet_request,
        )

        if result.get("success"):
            return {
                "status": "success",
                "bet": result.get("bet"),
                "message": result.get("message", "Live bet placed successfully"),
            }
        else:
            return {
                "status": "error",
                "error": result.get("error", "Failed to place live bet"),
            }

    except Exception as e:
        logger.error(f"Error placing live bet: {e}")
        raise HTTPException(status_code=500, detail="Failed to place live bet")


# Sports data endpoints
@app.get("/api/games/nfl")
async def get_nfl_games():
    """Get NFL games and scores"""
    if is_service_available("sports_pipeline"):
        try:
            sports_pipeline = get_service("sports_pipeline")
            games = await sports_pipeline.get_nfl_games_today()
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
                "status": "scheduled",
            }
        ],
        "message": "Mock data - Sports pipeline not fully configured",
    }


# AI Chat endpoints
@app.post("/api/chat/message")
async def send_chat_message(request: ChatRequest):
    """Send a message to AI chat service"""
    if is_service_available("ai_chat_service"):
        try:
            ai_chat = get_service("ai_chat_service")
            response = await ai_chat.send_message(
                request.message, request.conversation_history or []
            )
            return {"status": "success", "response": response}
        except Exception as e:
            logger.error(f"AI chat error: {e}")

    return {
        "status": "success",
        "response": {
            "role": "assistant",
            "content": f"I'm currently in {settings.ENVIRONMENT} mode with limited AI capabilities. Here's some general sports betting advice: Always bet responsibly and never wager more than you can afford to lose!",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "message": "Mock response - AI chat service not fully configured",
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
            "What should I know about tonight's matchup?",
        ],
    }


@app.get("/api/admin/featured-games")
async def get_featured_games(db=Depends(get_db)):
    """Get admin-selected featured games"""
    try:
        from sqlalchemy import text

        # Clean up expired games first
        cleanup_query = text("DELETE FROM featured_games WHERE start_time <= NOW()")
        db.execute(cleanup_query)
        db.commit()

        # First, try to get featured games from database (only future games)
        query = text(
            """
            SELECT game_id, home_team, away_team, start_time,
                   sport_key, explanation, admin_notes, created_at
            FROM featured_games
            WHERE start_time > NOW()
            ORDER BY start_time ASC
        """
        )

        result = db.execute(query)
        rows = result.fetchall()

        featured_games = []
        for row in rows:
            featured_games.append(
                {
                    "id": row.game_id,
                    "game_id": row.game_id,
                    "home_team": row.home_team,
                    "away_team": row.away_team,
                    "start_time": (
                        row.start_time.replace(tzinfo=timezone.utc).isoformat()
                        if row.start_time
                        else None
                    ),
                    "commence_time": (
                        row.start_time.replace(tzinfo=timezone.utc).isoformat()
                        if row.start_time
                        else None
                    ),
                    "sport_key": row.sport_key,
                    "status": "scheduled",
                    "explanation": row.explanation,
                    "admin_notes": row.admin_notes,
                }
            )

        # If no featured games in database, return empty
        if not featured_games:
            logger.info("No featured games found in database")

        return {"status": "success", "featured_games": featured_games}
    except Exception as e:
        logger.error(f"Error getting featured games: {e}")

        # If the error is about table not existing, try to create it
        if "featured_games" in str(e) and "does not exist" in str(e):
            try:
                logger.info("Featured games table doesn't exist, creating it...")
                # Create featured_games table
                create_table_sql = text(
                    """
                    CREATE TABLE IF NOT EXISTS featured_games (
                        id SERIAL PRIMARY KEY,
                        game_id VARCHAR(100) NOT NULL,
                        home_team VARCHAR(100) NOT NULL,
                        away_team VARCHAR(100) NOT NULL,
                        start_time TIMESTAMP NOT NULL,
                        sport_key VARCHAR(50) NOT NULL,
                        explanation TEXT NOT NULL,
                        admin_notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )
                db.execute(create_table_sql)
                db.commit()
                logger.info("Featured games table created successfully")

                # Return empty list since table was just created
                return {"status": "success", "featured_games": []}
            except Exception as create_error:
                logger.error(f"Failed to create featured games table: {create_error}")

        return {"status": "error", "featured_games": []}


@app.get("/api/featured-games")
async def get_public_featured_games(db=Depends(get_db)):
    """Get featured games for public display"""
    try:
        from sqlalchemy import text

        # Clean up expired games first
        cleanup_query = text("DELETE FROM featured_games WHERE start_time <= NOW()")
        db.execute(cleanup_query)
        db.commit()

        # Get only upcoming featured games for public display
        query = text(
            """
            SELECT game_id, home_team, away_team, start_time,
                   sport_key, explanation
            FROM featured_games
            WHERE start_time > NOW()
            ORDER BY start_time ASC
            LIMIT 10
        """
        )

        result = db.execute(query)
        rows = result.fetchall()

        featured_games = []
        for row in rows:
            featured_games.append(
                {
                    "id": row.game_id,
                    "game_id": row.game_id,
                    "home_team": row.home_team,
                    "away_team": row.away_team,
                    "start_time": (
                        row.start_time.replace(tzinfo=timezone.utc).isoformat()
                        if row.start_time
                        else None
                    ),
                    "commence_time": (
                        row.start_time.replace(tzinfo=timezone.utc).isoformat()
                        if row.start_time
                        else None
                    ),
                    "sport_key": row.sport_key,
                    "status": "scheduled",
                    "explanation": row.explanation,
                }
            )

        return {"status": "success", "featured_games": featured_games}
    except Exception as e:
        logger.error(f"Error getting public featured games: {e}")
        return {"status": "error", "featured_games": []}


@app.delete("/api/admin/featured-games/cleanup")
async def cleanup_expired_featured_games(
    admin_user: dict = Depends(require_admin), db=Depends(get_db)
):
    """Remove expired featured games (games that have already ended)"""
    try:
        from sqlalchemy import text

        # Delete games that have already ended
        cleanup_query = text("DELETE FROM featured_games WHERE start_time <= NOW()")
        result = db.execute(cleanup_query)
        db.commit()

        expired_count = result.rowcount if hasattr(result, "rowcount") else 0

        return {
            "status": "success",
            "message": f"Cleaned up {expired_count} expired featured games",
            "expired_removed": expired_count,
        }
    except Exception as e:
        logger.error(f"Error cleaning up expired featured games: {e}")
        return {
            "status": "error",
            "message": f"Failed to cleanup expired games: {str(e)}",
        }


@app.post("/api/admin/featured-games")
async def set_featured_games(request: dict, db=Depends(get_db)):
    """Set admin-selected featured games with explanations"""
    try:
        from sqlalchemy import text

        featured_games_data = request.get("featured_games", [])

        # First, clean up expired games (games that have already ended)
        cleanup_query = text("DELETE FROM featured_games WHERE start_time <= NOW()")
        cleanup_result = db.execute(cleanup_query)
        expired_count = (
            cleanup_result.rowcount if hasattr(cleanup_result, "rowcount") else 0
        )

        # Clear existing featured games
        db.execute(text("DELETE FROM featured_games"))

        # Insert new featured games
        for game_data in featured_games_data:
            insert_query = text(
                """
                INSERT INTO featured_games (
                    game_id, home_team, away_team, start_time,
                    sport_key, explanation, admin_notes, created_at
                ) VALUES (
                    :game_id, :home_team, :away_team, :start_time,
                    :sport_key, :explanation, :admin_notes, NOW()
                )
            """
            )

            db.execute(
                insert_query,
                {
                    "game_id": game_data.get("game_id"),
                    "home_team": game_data.get("home_team"),
                    "away_team": game_data.get("away_team"),
                    "start_time": game_data.get("start_time"),
                    "sport_key": game_data.get("sport_key", "americanfootball_nfl"),
                    "explanation": game_data.get("explanation", ""),
                    "admin_notes": game_data.get("admin_notes", ""),
                },
            )

        db.commit()

        message = f"Featured games updated with {len(featured_games_data)} games"
        if expired_count > 0:
            message += f" (removed {expired_count} expired games)"

        return {
            "status": "success",
            "message": message,
            "count": len(featured_games_data),
            "expired_removed": expired_count,
        }
    except Exception as e:
        logger.error(f"Error setting featured games: {e}")

        # If the error is about table not existing, try to create it and retry
        if "featured_games" in str(e) and "does not exist" in str(e):
            try:
                logger.info("Featured games table doesn't exist, creating it...")
                # Create featured_games table
                create_table_sql = text(
                    """
                    CREATE TABLE IF NOT EXISTS featured_games (
                        id SERIAL PRIMARY KEY,
                        game_id VARCHAR(100) NOT NULL,
                        home_team VARCHAR(100) NOT NULL,
                        away_team VARCHAR(100) NOT NULL,
                        start_time TIMESTAMP NOT NULL,
                        sport_key VARCHAR(50) NOT NULL,
                        explanation TEXT NOT NULL,
                        admin_notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )
                db.execute(create_table_sql)
                db.commit()
                logger.info("Featured games table created successfully")

                # Retry the original operation
                featured_games_data = request.get("featured_games", [])

                # Clear existing featured games (will be empty since table just created)
                db.execute(text("DELETE FROM featured_games"))

                # Insert new featured games
                for game_data in featured_games_data:
                    insert_query = text(
                        """
                        INSERT INTO featured_games (
                            game_id, home_team, away_team, start_time,
                            sport_key, explanation, admin_notes, created_at
                        ) VALUES (
                            :game_id, :home_team, :away_team, :start_time,
                            :sport_key, :explanation, :admin_notes, NOW()
                        )
                    """
                    )

                    db.execute(
                        insert_query,
                        {
                            "game_id": game_data.get("game_id"),
                            "home_team": game_data.get("home_team"),
                            "away_team": game_data.get("away_team"),
                            "start_time": game_data.get("start_time"),
                            "sport_key": game_data.get(
                                "sport_key", "americanfootball_nfl"
                            ),
                            "explanation": game_data.get("explanation", ""),
                            "admin_notes": game_data.get("admin_notes", ""),
                        },
                    )

                db.commit()

                return {
                    "status": "success",
                    "message": f"Featured games table created and updated with {len(featured_games_data)} games",
                    "count": len(featured_games_data),
                }
            except Exception as create_error:
                logger.error(f"Failed to create featured games table: {create_error}")

        return {
            "status": "error",
            "message": f"Failed to update featured games: {str(e)}",
        }


@app.get("/api/insights/today")
async def get_todays_insights():
    """Get AI insights for today's slate of games by league"""
    try:
        insights = []

        # Get today's games for major leagues
        leagues = ["nfl", "nba", "nhl", "mlb"]

        for league in leagues:
            try:
                # Get games for this league
                # Only support NFL for now to avoid undefined function
                if league == "nfl" and is_service_available("sports_pipeline"):
                    sports_pipeline = get_service("sports_pipeline")
                    games = await sports_pipeline.get_nfl_games_today()
                    response = {"status": "success", "games": games}
                else:
                    response = {"status": "success", "games": []}

                if response["status"] == "success" and "games" in response:
                    games = response["games"]

                    # Only add insights if there are games today
                    if games and len(games) > 0:
                        # Filter for today's games only
                        from datetime import datetime, timezone

                        today = datetime.now(timezone.utc).date()

                        todays_games = []
                        for game in games:
                            if game.get("commence_time"):
                                try:
                                    game_date = datetime.fromisoformat(
                                        game["commence_time"].replace("Z", "+00:00")
                                    ).date()
                                    if game_date == today:
                                        todays_games.append(game)
                                except:
                                    continue

                        if todays_games:
                            # Create league-specific insights
                            league_name = league.upper()
                            game_count = len(todays_games)

                            # Different insights based on league
                            if league == "nfl":
                                insights.append(
                                    {
                                        "title": f"{league_name} Week Analysis",
                                        "content": f"Today features {game_count} NFL games. Weather conditions and injury reports will be key factors. Focus on divisional matchups for higher unpredictability.",
                                        "confidence": 85,
                                        "category": "trend",
                                        "league": league_name,
                                    }
                                )
                            elif league == "nba":
                                insights.append(
                                    {
                                        "title": f"{league_name} Daily Slate",
                                        "content": f"{game_count} NBA games today. Look for back-to-back situations and rest advantages. Pace and total scoring trends favor overs in recent weeks.",
                                        "confidence": 78,
                                        "category": "trend",
                                        "league": league_name,
                                    }
                                )
                            elif league == "nhl":
                                insights.append(
                                    {
                                        "title": f"{league_name} Ice Analysis",
                                        "content": f"{game_count} NHL games scheduled. Goalie matchups and recent form are crucial. Home ice advantage more pronounced in cold weather months.",
                                        "confidence": 82,
                                        "category": "trend",
                                        "league": league_name,
                                    }
                                )
                            elif league == "mlb":
                                insights.append(
                                    {
                                        "title": f"{league_name} Diamond Insights",
                                        "content": f"{game_count} MLB games today. Weather and wind conditions significantly impact totals. Starting pitcher form and bullpen usage patterns are key.",
                                        "confidence": 80,
                                        "category": "weather",
                                        "league": league_name,
                                    }
                                )

                            # Add game-specific insight for leagues with fewer games
                            if game_count <= 3 and todays_games:
                                best_game = todays_games[0]
                                home_team = best_game.get("home_team", "Home")
                                away_team = best_game.get("away_team", "Away")

                                insights.append(
                                    {
                                        "title": f"Featured {league_name} Matchup",
                                        "content": f"{away_team} @ {home_team} stands out as today's most intriguing matchup with strong betting value potential.",
                                        "confidence": 75,
                                        "category": "value",
                                        "league": league_name,
                                    }
                                )

            except Exception as e:
                logger.warning(f"Error getting insights for {league}: {e}")
                continue

        # If no insights were generated, add a general insight
        if not insights:
            insights.append(
                {
                    "title": "Market Analysis",
                    "content": "Limited game slate today. Focus on quality over quantity and look for value in lesser-followed markets.",
                    "confidence": 70,
                    "category": "trend",
                    "league": "GENERAL",
                }
            )

        return {"status": "success", "insights": insights}

    except Exception as e:
        logger.error(f"Error generating today's insights: {e}")
        return {
            "status": "success",
            "insights": [
                {
                    "title": "System Update",
                    "content": "Insights service temporarily unavailable. Check back shortly for today's analysis.",
                    "confidence": 60,
                    "category": "trend",
                    "league": "SYSTEM",
                }
            ],
        }


# Comprehensive endpoint health check
@app.get("/api/endpoints/health")
async def endpoint_health_check():
    """Comprehensive health check for all API endpoints"""

    endpoint_categories = {
        "Core API": {"endpoints": ["/health", "/", "/api/status"], "operational": True},
        "Authentication": {
            "endpoints": [
                "/api/auth/status",
                "/api/auth/register",
                "/api/auth/login",
                "/api/auth/me",
            ],
            "operational": is_service_available("auth_service"),
        },
        "YetAI Bets": {
            "endpoints": ["/api/yetai-bets", "/api/admin/yetai-bets/{bet_id}"],
            "operational": is_service_available("yetai_bets_service"),
        },
        "Sports Betting": {
            "endpoints": [
                "/api/bets/place",
                "/api/bets/parlay",
                "/api/bets/parlays",
                "/api/bets/history",
                "/api/bets/stats",
                "/api/bets/share",
                "/api/bets/shared",
                "/api/bets/simulate",
            ],
            "operational": is_service_available("bet_service"),
        },
        "Fantasy Sports": {
            "endpoints": [
                "/api/fantasy/accounts",
                "/api/fantasy/leagues",
                "/api/fantasy/connect",
                "/api/fantasy/projections",
            ],
            "operational": is_service_available("fantasy_pipeline"),
        },
        "Odds & Markets": {
            "endpoints": [
                "/api/odds/americanfootball_nfl",
                "/api/odds/americanfootball_ncaaf",
                "/api/odds/basketball_nba",
                "/api/odds/baseball_mlb",
                "/api/odds/icehockey_nhl",
                "/api/odds/popular",
            ],
            "operational": bool(settings.ODDS_API_KEY),
        },
        "Parlays": {
            "endpoints": ["/api/parlays/markets", "/api/parlays/popular"],
            "operational": is_service_available("bet_service"),
        },
        "Profile & Status": {
            "endpoints": ["/api/profile/sports", "/api/profile/status"],
            "operational": is_service_available("auth_service"),
        },
        "Live Betting": {
            "endpoints": ["/api/live-bets/markets", "/api/live-bets/active"],
            "operational": is_service_available("bet_service"),
        },
        "AI Chat": {
            "endpoints": ["/api/chat/message", "/api/chat/suggestions"],
            "operational": is_service_available("ai_chat_service"),
        },
        "Sports Data": {
            "endpoints": ["/api/games/nfl"],
            "operational": is_service_available("sports_pipeline"),
        },
    }

    operational_count = sum(
        1 for cat in endpoint_categories.values() if cat["operational"]
    )
    total_count = len(endpoint_categories)

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "categories": endpoint_categories,
        "summary": {
            "operational_categories": operational_count,
            "total_categories": total_count,
            "health_percentage": round((operational_count / total_count) * 100, 1),
        },
        "services": service_loader.get_status(),
        "environment": settings.ENVIRONMENT,
    }


# Test endpoint for database connectivity
@app.get("/test-db")
async def test_database():
    """Test database connection with detailed debugging"""
    debug_info = {
        "environment": settings.ENVIRONMENT,
        "database_url": (
            settings.DATABASE_URL[:50] + "..."
            if len(settings.DATABASE_URL) > 50
            else settings.DATABASE_URL
        ),
        "service_available": is_service_available("database"),
    }

    if not is_service_available("database"):
        return {
            "status": "unavailable",
            "message": "Database service not loaded",
            "debug": debug_info,
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
                "message": (
                    "Database connection successful"
                    if connected
                    else "Database connection failed"
                ),
                "debug": debug_info,
            }
        else:
            debug_info["check_function_available"] = False
            return {
                "status": "error",
                "message": "Database check function not available",
                "debug": debug_info,
            }
    except Exception as e:
        debug_info["exception"] = str(e)
        debug_info["exception_type"] = str(type(e))
        return {
            "status": "error",
            "message": f"Database test failed: {str(e)}",
            "debug": debug_info,
        }


# Scheduler status endpoint for debugging
@app.get("/scheduler-status")
async def get_scheduler_status():
    """Get bet verification scheduler status (for debugging)"""
    try:
        stats = bet_scheduler.get_stats()
        return {
            "status": "success",
            "scheduler_stats": stats,
            "scheduler_running": bet_scheduler._running,
            "scheduler_enabled": bet_scheduler.config.enabled,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "scheduler_running": False,
        }


# Manual scheduler restart endpoint
@app.post("/restart-scheduler")
async def restart_scheduler():
    """Restart the bet verification scheduler (for debugging)"""
    try:
        # Stop current scheduler if running
        bet_scheduler.stop()

        # Wait a moment
        import asyncio

        await asyncio.sleep(2)

        # Start scheduler
        bet_scheduler.start()

        return {
            "status": "success",
            "message": "Scheduler restarted successfully",
            "scheduler_running": bet_scheduler._running,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to restart scheduler",
        }


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(message)
            except:
                self.disconnect(user_id)

    async def broadcast(self, message: str):
        disconnected = []
        for user_id, connection in self.active_connections.items():
            try:
                await connection.send_text(message)
            except:
                disconnected.append(user_id)

        for user_id in disconnected:
            self.disconnect(user_id)


# Analytics endpoints with frontend-compatible URLs
@app.get("/api/fantasy/analytics/{player_id}")
async def get_player_analytics_alt(
    player_id: str,
    season: int = 2025,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player analytics (alternative URL format)"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        analytics_service = PlayerAnalyticsService(db)

        # Map Sleeper player ID to internal player ID
        internal_player_id = None
        try:
            # Query database for the mapping
            fantasy_player_query = db.execute(
                text(
                    "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
                ),
                {"sleeper_id": str(player_id)},
            )
            fantasy_player_row = fantasy_player_query.fetchone()

            if fantasy_player_row:
                internal_player_id = fantasy_player_row[0]
                logger.info(
                    f"Mapped Sleeper ID {player_id} to internal ID {internal_player_id}"
                )
            else:
                logger.warning(f"No mapping found for Sleeper ID {player_id}")

        except Exception as e:
            logger.warning(f"Error mapping player ID {player_id}: {e}")

        analytics = []
        if internal_player_id:
            analytics = await analytics_service.get_player_analytics(
                internal_player_id, season=season
            )

        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "analytics": analytics or [],
        }
    except Exception as e:
        logger.error(f"Error getting player analytics for {player_id}: {e}")
        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "analytics": [],
        }


@app.get("/api/fantasy/analytics/{player_id}/trends")
async def get_player_trends_alt(
    player_id: str,
    season: int = 2025,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player trends (alternative URL format)"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        # Map Sleeper player ID to internal ID
        fantasy_player_query = db.execute(
            text(
                "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
            ),
            {"sleeper_id": str(player_id)},
        )
        fantasy_player = fantasy_player_query.fetchone()

        if not fantasy_player:
            return {
                "status": "error",
                "message": f"Player not found with ID: {player_id}",
                "trends": {},
            }

        internal_player_id = fantasy_player[0]
        analytics_service = PlayerAnalyticsService(db)

        # Get analytics and derive trends
        analytics = await analytics_service.get_player_analytics(
            internal_player_id, season=season
        )

        trends = {}
        if analytics and len(analytics) >= 2:
            recent = analytics[:3]  # Last 3 games
            older = analytics[3:6]  # Previous 3 games

            if recent and older:
                recent_avg = sum(g.get("ppr_points", 0) for g in recent) / len(recent)
                older_avg = sum(g.get("ppr_points", 0) for g in older) / len(older)

                trends = {
                    "trend_direction": "up" if recent_avg > older_avg else "down",
                    "recent_avg": round(recent_avg, 1),
                    "previous_avg": round(older_avg, 1),
                    "games_analyzed": len(recent) + len(older),
                }

        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "trends": trends,
        }
    except Exception as e:
        logger.error(f"Error getting player trends for {player_id}: {e}")
        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "trends": {},
        }


@app.get("/api/fantasy/analytics/{player_id}/efficiency")
async def get_player_efficiency_alt(
    player_id: str,
    season: int = 2025,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player efficiency (alternative URL format)"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService
        from sqlalchemy import text

        # Map Sleeper player ID to internal ID
        fantasy_player_query = db.execute(
            text(
                "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
            ),
            {"sleeper_id": str(player_id)},
        )
        fantasy_player = fantasy_player_query.fetchone()

        if not fantasy_player:
            return {
                "status": "error",
                "message": f"Player not found with ID: {player_id}",
                "efficiency": {},
            }

        internal_player_id = fantasy_player[0]
        analytics_service = PlayerAnalyticsService(db)

        # Get analytics and calculate efficiency metrics
        analytics = await analytics_service.get_player_analytics(
            internal_player_id, season=season
        )

        efficiency = {}
        if analytics:
            total_points = sum(g.get("ppr_points", 0) for g in analytics)
            total_snaps = sum(
                g.get("snap_percentage", 0)
                for g in analytics
                if g.get("snap_percentage")
            )
            total_targets = sum(
                g.get("target_share", 0) for g in analytics if g.get("target_share")
            )

            if total_snaps > 0:
                efficiency["points_per_snap"] = round(
                    total_points / total_snaps * 100, 2
                )
            if total_targets > 0:
                efficiency["points_per_target"] = round(
                    total_points / total_targets * 100, 2
                )

            efficiency["games_played"] = len(analytics)
            efficiency["total_points"] = round(total_points, 1)

        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "efficiency": efficiency,
        }
    except Exception as e:
        logger.error(f"Error getting player efficiency for {player_id}: {e}")
        return {
            "status": "success",
            "player_id": str(player_id),
            "season": season,
            "efficiency": {},
        }


# Trade Analyzer Endpoints
@app.get("/api/v1/fantasy/trade-analyzer/team-analysis/{team_id}")
async def get_simple_team_analysis(
    team_id: int, league_id: int = None, current_user: dict = Depends(get_current_user)
):
    """Get team analysis - REAL DATA ONLY, fetched directly from Sleeper API"""
    logger.info(
        f"🔍 TEAM ANALYSIS CALLED - Team: {team_id}, League: {league_id}, User: {current_user['user_id']}"
    )

    if not league_id:
        raise HTTPException(status_code=400, detail="league_id parameter is required")

    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get teams and standings data from Sleeper API
        logger.info(f"🔍 GETTING LEAGUE DATA from Sleeper API for league {league_id}")
        teams = await sleeper_service.get_league_teams(str(league_id))

        # Get standings data directly from SleeperFantasyService
        logger.info(
            f"🔍 GETTING STANDINGS DATA from Sleeper API for league {league_id}"
        )
        try:
            standings_data = await sleeper_service.get_league_standings(str(league_id))
            logger.info(f"🔍 FOUND {len(standings_data)} teams in standings")
        except Exception as e:
            logger.warning(f"Error fetching standings: {e}")
            standings_data = []

        # Find the specific team by team_id from both teams and standings
        team_data = None
        standings_team_data = None

        # Find team in teams data
        for team in teams:
            if team.get("team_id") == team_id or str(team.get("team_id")) == str(
                team_id
            ):
                team_data = team
                break

        # Find team in standings data
        for team in standings_data:
            if (
                team.get("team_id") == str(team_id)
                or int(team.get("team_id", 0)) == team_id
            ):
                standings_team_data = team
                break

        if not team_data:
            logger.warning(
                f"Team {team_id} not found in teams data, using first available team"
            )
            team_data = teams[0] if teams else {}

        if not standings_team_data:
            logger.warning(f"Team {team_id} not found in standings data")
            standings_team_data = {}

        # Get roster data for this team from Sleeper API
        logger.info(f"🔍 GETTING ROSTER DATA from Sleeper API")
        roster_data = []
        try:
            # Use direct HTTP call to get rosters like the roster endpoint does
            import aiohttp

            async with aiohttp.ClientSession() as session:
                roster_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
                async with session.get(roster_url) as response:
                    if response.status == 200:
                        rosters = await response.json()

                        # Find the roster for this team
                        target_roster = None
                        for roster in rosters:
                            if roster.get("roster_id") == team_id or str(
                                roster.get("roster_id")
                            ) == str(team_id):
                                target_roster = roster
                                break

                        if target_roster and target_roster.get("players"):
                            # Get player details
                            player_ids = target_roster["players"]
                            all_players = await sleeper_service._get_all_players()

                            for player_id in player_ids:
                                if player_id in all_players:
                                    player = all_players[player_id]
                                    # Convert player_id to integer for frontend compatibility
                                    numeric_id = (
                                        int(player_id)
                                        if player_id.isdigit()
                                        else hash(player_id) % 2147483647
                                    )

                                    # Calculate realistic trade value based on player data
                                    trade_value = calculate_realistic_trade_value(
                                        player
                                    )

                                    roster_data.append(
                                        {
                                            "id": numeric_id,  # Frontend expects 'id' field
                                            "player_id": player_id,  # Keep original for reference
                                            "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                                            "position": player.get(
                                                "position", "UNKNOWN"
                                            ),
                                            "team": player.get("team", "UNKNOWN"),
                                            "age": player.get("age", 0),
                                            "trade_value": trade_value,
                                        }
                                    )

                            logger.info(
                                f"🔍 FOUND {len(roster_data)} players for team {team_id}"
                            )
                        else:
                            logger.warning(f"No roster found for team {team_id}")
                    else:
                        logger.error(f"Failed to fetch rosters: {response.status}")

        except Exception as roster_error:
            logger.error(f"Error fetching roster: {roster_error}")
            roster_data = []

        # Build comprehensive team analysis response
        logger.info(
            f"🔍 TEAM ANALYSIS COMPLETE: {len(roster_data)} players for team {team_data.get('name', f'Team {team_id}')}"
        )

        # Calculate position analysis
        position_counts = {}
        position_strengths = {}
        position_needs = {}

        for player in roster_data:
            pos = player["position"]
            position_counts[pos] = position_counts.get(pos, 0) + 1

        # Calculate strengths and needs based on roster composition
        for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            count = position_counts.get(pos, 0)
            position_strengths[pos] = count * 20  # Strength based on player count

            # Determine need level (higher = more need)
            if pos == "QB":
                position_needs[pos] = 3 if count < 2 else 1
            elif pos in ["RB", "WR"]:
                position_needs[pos] = 3 if count < 3 else 1
            elif pos == "TE":
                position_needs[pos] = 3 if count < 2 else 1
            else:
                position_needs[pos] = 3 if count < 1 else 1

        # Identify surplus positions
        surplus_positions = []
        for pos, count in position_counts.items():
            if (
                (pos == "WR" and count > 4)
                or (pos == "RB" and count > 3)
                or (pos in ["QB", "TE"] and count > 2)
            ):
                surplus_positions.append(pos)

        # Sort players by trade value (highest to lowest)
        sorted_players = sorted(
            roster_data, key=lambda p: p.get("trade_value", 0), reverse=True
        )

        # Create tradeable assets lists based on actual trade value
        valuable_players = sorted_players[:5]  # Top 5 most valuable players
        expendable_players = (
            sorted_players[-5:] if len(sorted_players) > 5 else []
        )  # Bottom 5 least valuable players
        surplus_players = sorted_players[
            :8
        ]  # Top players that could be traded for good value

        # Merge team data with standings data for complete info
        merged_team_data = {**team_data, **standings_team_data}

        team_analysis = {
            "team_info": {
                "team_name": merged_team_data.get("name", f"Team {team_id}"),
                "record": {
                    "wins": merged_team_data.get("wins", 0),
                    "losses": merged_team_data.get("losses", 0),
                },
                "points_for": float(merged_team_data.get("points_for", 0.0)),
                "team_rank": merged_team_data.get("rank", 0),
                "competitive_tier": "competitive",  # Could be calculated based on record
            },
            "roster_analysis": {
                "position_strengths": position_strengths,
                "position_needs": position_needs,
                "surplus_positions": surplus_positions,
            },
            "tradeable_assets": {
                "surplus_players": surplus_players,
                "expendable_players": expendable_players,
                "valuable_players": valuable_players,
                "tradeable_picks": [
                    {
                        "pick_id": 1,
                        "season": 2025,
                        "round": 1,
                        "description": "2025 1st Round Pick",
                        "trade_value": 35,
                    },
                    {
                        "pick_id": 2,
                        "season": 2025,
                        "round": 2,
                        "description": "2025 2nd Round Pick",
                        "trade_value": 18,
                    },
                    {
                        "pick_id": 3,
                        "season": 2025,
                        "round": 3,
                        "description": "2025 3rd Round Pick",
                        "trade_value": 8,
                    },
                ],
            },
            "trade_strategy": {
                "competitive_analysis": {},
                "trade_preferences": {},
                "recommended_approach": f"Based on roster analysis, consider strengthening {', '.join([pos for pos, need in position_needs.items() if need >= 3])} positions.",
            },
        }

        return {
            "success": True,
            "team_analysis": team_analysis,
            "roster": roster_data,
            "message": f"Found {len(roster_data)} players for {team_analysis['team_info']['team_name']}",
        }

    except Exception as e:
        logger.error(f"🚨 ERROR getting team analysis: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get team analysis: {str(e)}"
        )


@app.post("/api/v1/fantasy/trade-analyzer/recommendations")
async def generate_trade_recommendations(
    request: Dict[str, Any], current_user: dict = Depends(get_current_user)
):
    """Generate AI-powered trade recommendations for a team - REAL DATA ONLY"""
    league_id = request.get("league_id")
    team_id = request.get("team_id")

    logger.info(
        f"🔍 TRADE RECOMMENDATIONS CALLED - League: {league_id}, Team: {team_id}, User: {current_user['user_id']}"
    )

    if not league_id:
        raise HTTPException(status_code=400, detail="league_id is required")

    service_available = is_service_available("fantasy_pipeline")
    logger.info(f"🔍 FANTASY_PIPELINE SERVICE AVAILABLE: {service_available}")

    if not service_available:
        logger.error("🚨 FANTASY_PIPELINE SERVICE NOT AVAILABLE")
        raise HTTPException(
            status_code=503, detail="Fantasy pipeline service unavailable"
        )

    try:
        fantasy_service = get_service("fantasy_pipeline")

        # Get the specified team's roster directly from Sleeper API
        logger.info(f"🔍 GETTING ROSTER for team {team_id} in league {league_id}")

        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get roster data for the specific team
        roster = []
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                roster_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
                async with session.get(roster_url) as response:
                    if response.status == 200:
                        rosters = await response.json()

                        # Find the roster for the specified team
                        target_roster = None
                        for roster_data in rosters:
                            if roster_data.get("roster_id") == team_id or str(
                                roster_data.get("roster_id")
                            ) == str(team_id):
                                target_roster = roster_data
                                break

                        if target_roster and target_roster.get("players"):
                            all_players = await sleeper_service._get_all_players()

                            for player_id in target_roster["players"]:
                                if player_id in all_players:
                                    player = all_players[player_id]
                                    # Calculate realistic trade value for this player
                                    trade_value = calculate_realistic_trade_value(
                                        player
                                    )

                                    roster.append(
                                        {
                                            "player_id": player_id,
                                            "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                                            "position": player.get(
                                                "position", "UNKNOWN"
                                            ),
                                            "team": player.get("team", "UNKNOWN"),
                                            "age": player.get("age", 27),
                                            "trade_value": trade_value,
                                        }
                                    )

                            logger.info(
                                f"🔍 FOUND {len(roster)} players for team {team_id}"
                            )
                        else:
                            logger.warning(f"No roster found for team {team_id}")
                    else:
                        logger.error(f"Failed to fetch rosters: {response.status}")
        except Exception as roster_error:
            logger.error(f"Error fetching roster for team {team_id}: {roster_error}")

        if not roster:
            logger.error(
                f"🚨 NO ROSTER DATA FOUND for team {team_id} in league {league_id}"
            )
            raise HTTPException(
                status_code=404, detail=f"No roster data found for team {team_id}"
            )

        # Get league teams to suggest real trade partners
        try:
            league_teams = await sleeper_service.get_league_teams(str(league_id))

            # Filter out the selected team (not current user's team)
            other_teams = []
            for team in league_teams:
                if str(team.get("team_id")) != str(team_id):
                    other_teams.append(team)

            logger.info(
                f"🔍 FOUND {len(other_teams)} OTHER TEAMS in league for trade suggestions"
            )

        except Exception as teams_error:
            logger.warning(f"Could not get league teams: {teams_error}")
            other_teams = []

        # Generate real recommendations based on the roster
        recommendations = []

        # Analyze roster by position
        positions = {}
        for player in roster:
            pos = player.get("position", "UNKNOWN")
            if pos not in positions:
                positions[pos] = []
            positions[pos].append(player)

        logger.info(
            f"🔍 ROSTER ANALYSIS: {[(pos, len(players)) for pos, players in positions.items()]}"
        )

        # Generate recommendations based on roster composition
        rec_id = 1

        # Helper function to format players for frontend
        def format_players(player_data_list):
            """Convert player data to the format expected by frontend"""
            players = []
            for player_data in player_data_list:
                if isinstance(player_data, dict):
                    # Real player from roster
                    players.append(
                        {
                            "id": player_data.get(
                                "player_id",
                                f"player_{player_data['name'].replace(' ', '_')}",
                            ),
                            "name": player_data["name"],
                            "position": player_data.get("position", "UNKNOWN"),
                            "team": player_data.get("team", "UNKNOWN"),
                            "age": player_data.get("age", 27),
                        }
                    )
                else:
                    # Generic player name (string)
                    players.append(
                        {
                            "id": f"player_{player_data.replace(' ', '_')}",
                            "name": player_data,
                            "position": "UNKNOWN",
                            "team": "UNKNOWN",
                            "age": 26,
                        }
                    )
            return players

        # Helper function to get realistic trade partner
        def get_trade_partner():
            """Get a realistic trade partner from league teams"""
            if other_teams:
                import random

                partner = random.choice(other_teams)
                return {
                    "name": partner.get(
                        "name", f"Team {partner.get('team_id', 'Unknown')}"
                    ),
                    "team_id": partner.get("team_id"),
                    "full_data": partner,
                }
            return {"name": "League Team", "team_id": None, "full_data": None}

        # Helper function to get real players from target team
        async def get_target_team_players(target_team_id, position_needed):
            """Get real players from target team for the specified position"""
            if not target_team_id:
                return [
                    {
                        "id": "generic_player",
                        "name": f"Generic {position_needed}",
                        "position": position_needed,
                        "team": "UNK",
                        "age": 27,
                        "trade_value": 20.0,
                    }
                ]

            try:
                # Get roster for target team
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    roster_url = (
                        f"https://api.sleeper.app/v1/league/{league_id}/rosters"
                    )
                    async with session.get(roster_url) as response:
                        if response.status == 200:
                            rosters = await response.json()

                            # Find target team's roster
                            target_roster = None
                            for roster in rosters:
                                if str(roster.get("roster_id")) == str(target_team_id):
                                    target_roster = roster
                                    break

                            if target_roster and target_roster.get("players"):
                                all_players = await sleeper_service._get_all_players()
                                position_players = []

                                for player_id in target_roster["players"]:
                                    if player_id in all_players:
                                        player = all_players[player_id]
                                        if player.get("position") == position_needed:
                                            trade_value = (
                                                calculate_realistic_trade_value(player)
                                            )
                                            position_players.append(
                                                {
                                                    "id": player_id,
                                                    "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                                                    "position": player.get(
                                                        "position", position_needed
                                                    ),
                                                    "team": player.get(
                                                        "team", "UNKNOWN"
                                                    ),
                                                    "age": player.get("age", 27),
                                                    "trade_value": trade_value,
                                                }
                                            )

                                if position_players:
                                    # Return best player for that position
                                    return [
                                        max(
                                            position_players,
                                            key=lambda p: p["trade_value"],
                                        )
                                    ]

                # Fallback if no players found
                return [
                    {
                        "id": "backup_player",
                        "name": f"Available {position_needed}",
                        "position": position_needed,
                        "team": "UNKNOWN",
                        "age": 26,
                        "trade_value": 15.0,
                    }
                ]

            except Exception as e:
                logger.warning(f"Could not get target team players: {e}")
                return [
                    {
                        "id": "fallback_player",
                        "name": f"Backup {position_needed}",
                        "position": position_needed,
                        "team": "UNKNOWN",
                        "age": 25,
                        "trade_value": 12.0,
                    }
                ]

        # Helper function to add trade values to existing players
        def add_trade_values(players_list):
            """Add trade_value field to players that don't have it"""
            for player in players_list:
                if "trade_value" not in player:
                    # Create mock player data for trade value calculation
                    mock_player = {
                        "position": player.get("position", "UNKNOWN"),
                        "age": player.get(
                            "age", 27
                        ),  # Use player's actual age or default
                        "team": player.get("team", "UNKNOWN"),
                    }
                    player["trade_value"] = calculate_realistic_trade_value(mock_player)

                # Ensure age is present
                if "age" not in player:
                    player["age"] = 27  # Default age if not provided
            return players_list

        # Check for position weaknesses
        if len(positions.get("QB", [])) < 2:
            rb_players = positions.get("RB", [])[:1]
            trade_partner = get_trade_partner()

            # Get real QB from target team
            target_qb_players = await get_target_team_players(
                trade_partner["team_id"], "QB"
            )

            recommendations.append(
                {
                    "id": rec_id,
                    "recommendation_type": "QB Depth Needed",
                    "type": "depth_addition",
                    "title": "Add QB Depth",
                    "description": f"Consider trading for a backup quarterback from {trade_partner['name']}",
                    "target_team_id": trade_partner["team_id"],
                    "we_give": {
                        "players": add_trade_values(format_players(rb_players)),
                        "picks": [],
                    },
                    "we_get": {
                        "players": target_qb_players,
                        "picks": ["2025 Late Round Pick"],
                    },
                    "confidence": 75,
                    "estimated_likelihood": 0.75,
                    "priority_score": 60,
                    "reasoning": f"Limited QB depth could be problematic if starter gets injured. {trade_partner['name']} may have QB depth to spare.",
                    "trade_partner": trade_partner["name"],
                }
            )
            rec_id += 1

        if len(positions.get("RB", [])) > 4:
            rb_players = positions.get("RB", [])
            give_players = rb_players[
                -2:
            ]  # Trade least important RBs (actual player objects)
            trade_partner = get_trade_partner()

            # Get real players from target team
            target_wr_players = await get_target_team_players(
                trade_partner["team_id"], "WR"
            )
            target_te_players = await get_target_team_players(
                trade_partner["team_id"], "TE"
            )

            recommendations.append(
                {
                    "id": rec_id,
                    "recommendation_type": "RB Surplus Trade",
                    "type": "position_balance",
                    "title": "Trade Excess RB Depth",
                    "description": f"Trade surplus running backs to {trade_partner['name']} for position upgrades",
                    "target_team_id": trade_partner["team_id"],
                    "we_give": {
                        "players": add_trade_values(format_players(give_players)),
                        "picks": [],
                    },
                    "we_get": {
                        "players": target_wr_players + target_te_players,
                        "picks": [],
                    },
                    "confidence": 80,
                    "estimated_likelihood": 0.80,
                    "priority_score": 70,
                    "reasoning": f"With {len(rb_players)} RBs, you can afford to trade depth for upgrades at other positions. {trade_partner['name']} may need RB help.",
                    "trade_partner": trade_partner["name"],
                }
            )
            rec_id += 1

        if len(positions.get("WR", [])) < 4:
            te_players = (
                positions.get("TE", [])[:1] if len(positions.get("TE", [])) > 1 else []
            )
            trade_partner = get_trade_partner()

            # Get real WR from target team
            target_wr_players = await get_target_team_players(
                trade_partner["team_id"], "WR"
            )

            recommendations.append(
                {
                    "id": rec_id,
                    "recommendation_type": "WR Depth Needed",
                    "type": "depth_addition",
                    "title": "Add WR Depth",
                    "description": f"Target wide receiver depth from {trade_partner['name']} for better matchup flexibility",
                    "target_team_id": trade_partner["team_id"],
                    "we_give": {
                        "players": add_trade_values(format_players(te_players)),
                        "picks": ["Mid Round Pick"] if not te_players else [],
                    },
                    "we_get": {
                        "players": target_wr_players,
                        "picks": ["2026 Late Pick"],
                    },
                    "confidence": 70,
                    "estimated_likelihood": 0.70,
                    "priority_score": 55,
                    "reasoning": f"More WR depth provides better weekly lineup flexibility. {trade_partner['name']} may have WR depth to trade.",
                    "trade_partner": trade_partner["name"],
                }
            )
            rec_id += 1

        logger.info(f"🔍 GENERATED {len(recommendations)} RECOMMENDATIONS")

        return {
            "success": True,
            "team_id": team_id,
            "league_id": league_id,
            "recommendation_type": request.get("recommendation_type", "all"),
            "recommendation_count": len(recommendations),
            "recommendations": recommendations,
        }

    except Exception as e:
        logger.error(f"🚨 ERROR generating trade recommendations: {e}")
        import traceback

        logger.error(f"🚨 TRACEBACK: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate recommendations: {str(e)}"
        )


@app.get("/api/v1/fantasy/trade-analyzer/player-values")
async def get_player_values(
    limit: int = 200, current_user: dict = Depends(get_current_user)
):
    """Get player trade values for all players"""
    try:
        logger.info(f"Player values called with limit: {limit}")

        # Get Sleeper service for player data
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        all_players = await sleeper_service._get_all_players()

        # Get trending data for popularity boost
        trending_adds = await sleeper_service.get_trending_players("add")
        trending_lookup = {
            player.get("player_id"): player.get("trend_count", 0)
            for player in trending_adds
        }

        player_values = []

        for player_id, player_data in list(all_players.items())[:limit]:
            if not player_data.get("active", True):
                continue

            name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
            position = player_data.get("position", "UNKNOWN")

            # Skip non-fantasy positions
            if position not in ["QB", "RB", "WR", "TE", "K", "DEF"]:
                continue

            # Calculate trade value
            trade_value = calculate_realistic_trade_value(player_data)

            # Add trending boost
            trend_count = trending_lookup.get(player_id, 0)
            if trend_count > 0:
                trade_value *= 1 + (
                    trend_count / 100
                )  # Small boost for trending players

            player_values.append(
                {
                    "player_id": player_id,
                    "name": name,
                    "position": position,
                    "team": player_data.get("team", "FA"),
                    "age": player_data.get("age", 27),
                    "trade_value": round(trade_value, 1),
                    "trend_type": "hot" if trend_count > 0 else "neutral",
                    "trend_count": trend_count,
                }
            )

        # Sort by trade value descending
        player_values.sort(key=lambda p: p["trade_value"], reverse=True)

        logger.info(f"Returning {len(player_values)} player values")
        return {
            "success": True,
            "players": player_values,
            "total": len(player_values),
            "limit": limit,
        }

    except Exception as e:
        logger.error(f"Error getting player values: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get player values: {str(e)}"
        )


class QuickAnalysisRequest(BaseModel):
    league_id: str
    team1_id: int
    team2_id: int
    team1_gives: Dict[str, Any]
    team2_gives: Dict[str, Any]


@app.post("/api/v1/fantasy/trade-analyzer/quick-analysis")
async def quick_trade_analysis(
    request: QuickAnalysisRequest, current_user: dict = Depends(get_current_user)
):
    """Perform quick analysis of a proposed trade"""
    try:
        logger.info(
            f"Quick trade analysis called: {request.team1_id} vs {request.team2_id}"
        )

        # Get Sleeper service for player data
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        all_players = await sleeper_service._get_all_players()

        # Helper function to analyze trade side
        def analyze_trade_side(players_list, side_name):
            total_value = 0
            side_analysis = {
                "players": [],
                "total_value": 0,
                "positions": {},
                "avg_age": 0,
            }

            ages = []
            for player_id in players_list:
                if str(player_id) in all_players:
                    player_data = all_players[str(player_id)]
                    name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
                    position = player_data.get("position", "UNKNOWN")
                    age = player_data.get("age", 27)
                    trade_value = calculate_realistic_trade_value(player_data)

                    player_info = {
                        "player_id": player_id,
                        "name": name,
                        "position": position,
                        "team": player_data.get("team", "FA"),
                        "age": age,
                        "trade_value": round(trade_value, 1),
                    }

                    side_analysis["players"].append(player_info)
                    total_value += trade_value
                    ages.append(age)

                    # Track positions
                    if position in side_analysis["positions"]:
                        side_analysis["positions"][position] += 1
                    else:
                        side_analysis["positions"][position] = 1

            side_analysis["total_value"] = round(total_value, 1)
            side_analysis["avg_age"] = round(sum(ages) / len(ages) if ages else 0, 1)

            return side_analysis

        # Analyze both sides
        team1_gives = analyze_trade_side(
            request.team1_gives.get("players", []), "Team 1 Gives"
        )
        team2_gives = analyze_trade_side(
            request.team2_gives.get("players", []), "Team 2 Gives"
        )

        # Calculate trade fairness
        value_diff = abs(team1_gives["total_value"] - team2_gives["total_value"])
        total_value = team1_gives["total_value"] + team2_gives["total_value"]
        fairness_pct = (
            max(0, 100 - (value_diff / total_value * 100)) if total_value > 0 else 0
        )

        # Determine trade verdict
        if fairness_pct >= 90:
            verdict = "Fair Trade"
            verdict_color = "green"
        elif fairness_pct >= 75:
            verdict = "Slightly Uneven"
            verdict_color = "yellow"
        elif fairness_pct >= 60:
            verdict = "Uneven Trade"
            verdict_color = "orange"
        else:
            verdict = "Very Uneven"
            verdict_color = "red"

        # Generate comprehensive key factors/insights
        insights = []

        # Age analysis
        if team1_gives["avg_age"] > team2_gives["avg_age"] + 3:
            insights.append(
                f"Team 1 trading older players (avg age {team1_gives['avg_age']:.1f} vs {team2_gives['avg_age']:.1f})"
            )
        elif team2_gives["avg_age"] > team1_gives["avg_age"] + 3:
            insights.append(
                f"Team 2 trading older players (avg age {team2_gives['avg_age']:.1f} vs {team1_gives['avg_age']:.1f})"
            )

        # Value differential analysis
        if value_diff > 10:
            if team1_gives["total_value"] > team2_gives["total_value"]:
                insights.append(
                    f"Team 1 giving up {value_diff:.1f} more value - may need compensation"
                )
            else:
                insights.append(
                    f"Team 2 giving up {value_diff:.1f} more value - may need compensation"
                )

        # Player quantity analysis
        if len(team1_gives["players"]) > len(team2_gives["players"]) + 1:
            insights.append(
                "Team 1 trading multiple players for fewer elite players (talent consolidation)"
            )
        elif len(team2_gives["players"]) > len(team1_gives["players"]) + 1:
            insights.append(
                "Team 2 trading multiple players for fewer elite players (talent consolidation)"
            )

        # Position balance analysis
        team1_positions = list(team1_gives["positions"].keys())
        team2_positions = list(team2_gives["positions"].keys())

        if "QB" in team1_positions or "QB" in team2_positions:
            insights.append("QB involved - high-impact position trade")

        if "RB" in team1_positions and "WR" in team2_positions:
            insights.append("RB for WR swap - different positional strategies")
        elif "WR" in team1_positions and "RB" in team2_positions:
            insights.append("WR for RB swap - different positional strategies")

        # High-value player analysis
        team1_high_value = [p for p in team1_gives["players"] if p["trade_value"] > 25]
        team2_high_value = [p for p in team2_gives["players"] if p["trade_value"] > 25]

        if team1_high_value and not team2_high_value:
            insights.append(
                f"Team 1 trading elite player ({team1_high_value[0]['name']}) for depth"
            )
        elif team2_high_value and not team1_high_value:
            insights.append(
                f"Team 2 trading elite player ({team2_high_value[0]['name']}) for depth"
            )
        elif team1_high_value and team2_high_value:
            insights.append("Elite players on both sides - star-for-star trade")

        # Rookie/young player analysis
        team1_young = [p for p in team1_gives["players"] if p["age"] <= 24]
        team2_young = [p for p in team2_gives["players"] if p["age"] <= 24]

        if team1_young and not team2_young:
            insights.append("Team 1 trading young talent for immediate production")
        elif team2_young and not team1_young:
            insights.append("Team 2 trading young talent for immediate production")

        # Ensure we have at least some insights
        if not insights:
            if fairness_pct >= 85:
                insights.append("Values are well-matched - good trade balance")
            elif team1_gives["total_value"] > team2_gives["total_value"]:
                insights.append(
                    "Team 1 giving up more value - consider additional compensation"
                )
            else:
                insights.append(
                    "Team 2 giving up more value - consider additional compensation"
                )

        # Helper function to convert insight strings to structured objects
        def format_insight(insight_text):
            # Determine impact level and category based on content
            impact = "medium"  # default
            category = "general"  # default

            if "more value" in insight_text or "compensation" in insight_text:
                impact = "high"
                category = "value_analysis"
            elif "older players" in insight_text or "young talent" in insight_text:
                impact = "medium"
                category = "age_analysis"
            elif "QB" in insight_text:
                impact = "high"
                category = "position_strategy"
            elif "elite player" in insight_text or "star-for-star" in insight_text:
                impact = "high"
                category = "player_value"
            elif "consolidation" in insight_text or "multiple players" in insight_text:
                impact = "medium"
                category = "roster_construction"
            elif "well-matched" in insight_text or "good trade balance" in insight_text:
                impact = "low"
                category = "trade_balance"
            elif "swap" in insight_text or "strategies" in insight_text:
                impact = "medium"
                category = "position_strategy"

            return {"category": category, "description": insight_text, "impact": impact}

        # Convert insights to structured format
        structured_insights = [format_insight(insight) for insight in insights]

        return {
            "success": True,
            "analysis": {
                "trade_id": f"{request.team1_id}_{request.team2_id}_{int(time.time())}",
                "team1_gives": team1_gives,
                "team2_gives": team2_gives,
                "fairness": {
                    "percentage": round(fairness_pct, 1),
                    "verdict": verdict,
                    "verdict_color": verdict_color,
                    "value_difference": round(value_diff, 1),
                },
                "insights": structured_insights,
                "recommendation": verdict,
            },
        }

    except Exception as e:
        logger.error(f"Error in quick trade analysis: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze trade: {str(e)}"
        )


# Player comparison request model
class ComparePlayersRequest(BaseModel):
    player_ids: List[str]
    league_id: Optional[str] = None


@app.post("/api/fantasy/players/compare")
async def compare_players(
    request: ComparePlayersRequest, current_user: dict = Depends(get_current_user)
):
    """Compare multiple players side-by-side with analytics"""
    try:
        player_ids = request.player_ids
        league_id = request.league_id

        logger.info(
            f"Player comparison called with {len(player_ids)} players: {player_ids}"
        )

        if len(player_ids) < 2 or len(player_ids) > 4:
            raise HTTPException(status_code=400, detail="Must compare 2-4 players")

        # Get Sleeper service for player data
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()
        all_players = await sleeper_service._get_all_players()

        # Get trending data
        trending_adds = await sleeper_service.get_trending_players("add")
        trending_drops = await sleeper_service.get_trending_players("drop")
        trending_lookup = {}

        for player in trending_adds:
            trending_lookup[player.get("player_id")] = {
                "type": "hot",
                "count": player.get("trend_count", 0),
            }
        for player in trending_drops:
            if player.get("player_id") not in trending_lookup:
                trending_lookup[player.get("player_id")] = {
                    "type": "cold",
                    "count": player.get("trend_count", 0),
                }

        compared_players = []

        for player_id in player_ids:
            if player_id not in all_players:
                continue

            player_data = all_players[player_id]
            name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()

            # Build comparison data
            comparison_data = {
                "player_id": player_id,
                "name": name,
                "position": player_data.get("position", ""),
                "team": player_data.get("team", ""),
                "age": player_data.get("age"),
                "experience": player_data.get("years_exp"),
                "injury_status": player_data.get("injury_status", "Healthy"),
                "physical_stats": {
                    "height": player_data.get("height"),
                    "weight": player_data.get("weight"),
                },
                "career_info": {
                    "college": player_data.get("college"),
                    "draft_year": player_data.get("draft_year"),
                    "draft_round": player_data.get("draft_round"),
                    "draft_pick": player_data.get("draft_pick"),
                },
                "team_context": {
                    "depth_chart_order": player_data.get("depth_chart_order"),
                    "search_rank": player_data.get("search_rank", 999),
                },
                "trending": trending_lookup.get(
                    player_id, {"type": "normal", "count": 0}
                ),
                "fantasy_positions": player_data.get("fantasy_positions", []),
            }

            compared_players.append(comparison_data)

        return {
            "status": "success",
            "comparison": {
                "players": compared_players,
                "insights": [],  # Can add insights later
                "league_context": league_id,
                "comparison_date": datetime.utcnow().isoformat(),
            },
        }

    except Exception as e:
        logger.error(f"Error in player comparison: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fantasy/players/{player_id}/analytics/{season}")
async def get_player_analytics(
    player_id: str,
    season: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player analytics for a specific season"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService

        analytics_service = PlayerAnalyticsService(db)

        # Convert string player_id to int if needed
        try:
            player_id_int = int(player_id)
        except ValueError:
            # If it's a sleeper ID, we would need to map it
            # For now, return a mock response
            return {
                "status": "success",
                "player_id": player_id,
                "season": season,
                "analytics": {
                    "total_points": 0,
                    "avg_points_per_game": 0,
                    "games_played": 0,
                    "consistency_rating": "N/A",
                    "target_share": 0,
                    "red_zone_usage": 0,
                    "snap_percentage": 0,
                },
                "message": "Player analytics data not available",
            }

        # Get week list for the season (weeks 1-17 typically)
        week_list = list(range(1, 18))

        analytics = await analytics_service.get_player_analytics(
            player_id_int, week_list, season
        )

        return {
            "status": "success",
            "player_id": player_id,
            "season": season,
            "analytics": analytics,
        }

    except Exception as e:
        logger.error(f"Error getting player analytics: {str(e)}")
        return {
            "status": "error",
            "message": "Analytics data temporarily unavailable",
            "player_id": player_id,
            "season": season,
            "analytics": {},
        }


@app.get("/api/fantasy/players/{player_id}/trends/{season}")
async def get_player_trends(
    player_id: str,
    season: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player trend analysis for a specific season"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService

        analytics_service = PlayerAnalyticsService(db)

        try:
            player_id_int = int(player_id)
        except ValueError:
            return {
                "status": "success",
                "player_id": player_id,
                "season": season,
                "trends": {
                    "scoring_trend": "stable",
                    "usage_trend": "stable",
                    "efficiency_trend": "stable",
                    "recent_form": "average",
                },
                "message": "Player trends data not available",
            }

        week_list = list(range(1, 18))
        trends = await analytics_service.calculate_usage_trends(
            player_id_int, week_list, season
        )

        return {
            "status": "success",
            "player_id": player_id,
            "season": season,
            "trends": trends,
        }

    except Exception as e:
        logger.error(f"Error getting player trends: {str(e)}")
        return {
            "status": "error",
            "message": "Trends data temporarily unavailable",
            "player_id": player_id,
            "season": season,
            "trends": {},
        }


@app.get("/api/fantasy/players/{player_id}/efficiency/{season}")
async def get_player_efficiency(
    player_id: str,
    season: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get player efficiency metrics for a specific season"""
    try:
        from app.services.player_analytics_service import PlayerAnalyticsService

        analytics_service = PlayerAnalyticsService(db)

        try:
            player_id_int = int(player_id)
        except ValueError:
            return {
                "status": "success",
                "player_id": player_id,
                "season": season,
                "efficiency": {
                    "yards_per_target": 0,
                    "yards_per_carry": 0,
                    "red_zone_efficiency": 0,
                    "target_efficiency": 0,
                    "snap_efficiency": 0,
                },
                "message": "Player efficiency data not available",
            }

        week_list = list(range(1, 18))
        efficiency = await analytics_service.calculate_efficiency_metrics(
            player_id_int, week_list, season
        )

        return {
            "status": "success",
            "player_id": player_id,
            "season": season,
            "efficiency": efficiency,
        }

    except Exception as e:
        logger.error(f"Error getting player efficiency: {str(e)}")
        return {
            "status": "error",
            "message": "Efficiency data temporarily unavailable",
            "player_id": player_id,
            "season": season,
            "efficiency": {},
        }


# WebSocket manager instance
ws_manager = ConnectionManager()


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time updates"""
    try:
        await ws_manager.connect(websocket, user_id)
        logger.info(f"WebSocket connected for user {user_id}")

        # Send welcome message
        await ws_manager.send_personal_message(
            f'{{"type": "connection", "message": "Connected to YetAI real-time updates"}}',
            user_id,
        )

        while True:
            # Keep connection alive and handle incoming messages
            try:
                data = await websocket.receive_text()
                # Echo back received data (can be extended for specific functionality)
                await ws_manager.send_personal_message(
                    f'{{"type": "echo", "data": {data}}}', user_id
                )
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id)
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        ws_manager.disconnect(user_id)


@app.get("/api/debug/analytics-status")
async def debug_analytics_status(db=Depends(get_db)):
    """Debug endpoint to check analytics table status in production"""
    from sqlalchemy import text
    from datetime import datetime

    try:
        # Check if tables exist
        tables_check = db.execute(
            text(
                """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('player_analytics', 'player_trends', 'fantasy_players')
            ORDER BY table_name
        """
            )
        ).fetchall()

        # Count records in each table
        player_analytics_count = (
            db.execute(text("SELECT COUNT(*) FROM player_analytics")).fetchone()[0]
            if any(t[0] == "player_analytics" for t in tables_check)
            else 0
        )
        player_trends_count = (
            db.execute(text("SELECT COUNT(*) FROM player_trends")).fetchone()[0]
            if any(t[0] == "player_trends" for t in tables_check)
            else 0
        )
        fantasy_players_count = (
            db.execute(text("SELECT COUNT(*) FROM fantasy_players")).fetchone()[0]
            if any(t[0] == "fantasy_players" for t in tables_check)
            else 0
        )

        # Check seasons available
        seasons = []
        if player_analytics_count > 0:
            seasons_result = db.execute(
                text("SELECT DISTINCT season FROM player_analytics ORDER BY season")
            ).fetchall()
            seasons = [row[0] for row in seasons_result]

        # Test sample player lookup
        sample_player = None
        if fantasy_players_count > 0:
            sample_result = db.execute(
                text("SELECT id, platform_player_id, name FROM fantasy_players LIMIT 1")
            ).fetchone()
            if sample_result:
                sample_player = {
                    "fantasy_id": sample_result[0],
                    "platform_id": sample_result[1],
                    "name": sample_result[2],
                }

                # Check if this player has analytics (use fantasy_id, not platform_id)
                if player_analytics_count > 0:
                    analytics_count = db.execute(
                        text(
                            "SELECT COUNT(*) FROM player_analytics WHERE player_id = :pid"
                        ),
                        {"pid": sample_result[0]},
                    ).fetchone()[0]
                    sample_player["analytics_records"] = analytics_count

        return {
            "database_connected": True,
            "tables_exist": [t[0] for t in tables_check],
            "record_counts": {
                "player_analytics": player_analytics_count,
                "player_trends": player_trends_count,
                "fantasy_players": fantasy_players_count,
            },
            "available_seasons": seasons,
            "sample_player": sample_player,
            "debug_timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return {
            "error": str(e),
            "database_connected": False,
            "debug_timestamp": datetime.utcnow().isoformat(),
        }


@app.post("/api/admin/setup-featured-games")
async def setup_featured_games_table(db=Depends(get_db)):
    """Create featured_games table for admin curation"""
    try:
        from sqlalchemy import text

        # Create featured_games table
        create_table_sql = text(
            """
            CREATE TABLE IF NOT EXISTS featured_games (
                id SERIAL PRIMARY KEY,
                game_id VARCHAR(255) NOT NULL,
                home_team VARCHAR(255) NOT NULL,
                away_team VARCHAR(255) NOT NULL,
                start_time TIMESTAMP,
                sport_key VARCHAR(100) DEFAULT 'americanfootball_nfl',
                explanation TEXT,
                admin_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        db.execute(create_table_sql)
        db.commit()

        return {
            "status": "success",
            "message": "Featured games table created successfully",
        }
    except Exception as e:
        logger.error(f"Error creating featured games table: {e}")
        return {"status": "error", "message": f"Failed to create table: {str(e)}"}


@app.post("/api/admin/migrate-data")
async def migrate_production_data(db=Depends(get_db)):
    """Migration endpoint to populate production database with fantasy players and analytics data"""
    from sqlalchemy import text
    from datetime import datetime
    import os

    try:
        # First check the schema
        schema_query = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'fantasy_players'
            ORDER BY ordinal_position
        """
        columns_result = db.execute(text(schema_query)).fetchall()

        # Check current state
        analytics_count = db.execute(
            text("SELECT COUNT(*) FROM player_analytics")
        ).fetchone()[0]
        players_count = db.execute(
            text("SELECT COUNT(*) FROM fantasy_players")
        ).fetchone()[0]

        migration_log = []
        migration_log.append(
            f"Starting migration - Players: {players_count}, Analytics: {analytics_count}"
        )
        migration_log.append(
            f"Schema: {[(col[0], col[1], col[2]) for col in columns_result]}"
        )

        # Fantasy players data (try SLEEPER enum value)
        fantasy_players_inserts = [
            "INSERT INTO fantasy_players (platform, platform_player_id, name, position, team) VALUES ('SLEEPER', '4866', 'Saquon Barkley', 'RB', 'PHI');",
            "INSERT INTO fantasy_players (platform, platform_player_id, name, position, team) VALUES ('SLEEPER', '7588', 'Justin Jefferson', 'WR', 'MIN');",
        ]

        # Player analytics sample data
        analytics_inserts = [
            "INSERT INTO player_analytics (id, player_id, week, season, ppr_points, snap_percentage, target_share, red_zone_share, points_per_snap, points_per_target, boom_rate, bust_rate, floor_score, ceiling_score, opponent, injury_designation, game_script) VALUES (1, 4866, 1, 2024, 18.5, 65.2, 8.5, 15.0, 0.28, 1.85, 35.0, 10.0, 12.0, 25.0, 'GB', NULL, 2.1);",
            "INSERT INTO player_analytics (id, player_id, week, season, ppr_points, snap_percentage, target_share, red_zone_share, points_per_snap, points_per_target, boom_rate, bust_rate, floor_score, ceiling_score, opponent, injury_designation, game_script) VALUES (2, 4866, 2, 2024, 22.3, 68.1, 10.2, 18.5, 0.33, 2.18, 40.0, 8.0, 15.0, 28.0, 'ATL', NULL, 1.8);",
            "INSERT INTO player_analytics (id, player_id, week, season, ppr_points, snap_percentage, target_share, red_zone_share, points_per_snap, points_per_target, boom_rate, bust_rate, floor_score, ceiling_score, opponent, injury_designation, game_script) VALUES (3, 7588, 1, 2024, 24.7, 92.3, 28.5, 12.0, 0.27, 1.73, 60.0, 5.0, 18.0, 32.0, 'NYG', NULL, -1.2);",
            "INSERT INTO player_analytics (id, player_id, week, season, ppr_points, snap_percentage, target_share, red_zone_share, points_per_snap, points_per_target, boom_rate, bust_rate, floor_score, ceiling_score, opponent, injury_designation, game_script) VALUES (4, 7588, 2, 2024, 19.4, 89.7, 25.2, 8.5, 0.22, 1.55, 45.0, 8.0, 16.0, 28.0, 'SF', NULL, -2.8);",
        ]

        if players_count == 0:
            migration_log.append("Inserting fantasy players data...")
            for insert_sql in fantasy_players_inserts:
                db.execute(text(insert_sql))
            db.commit()

            # Check new count
            new_players_count = db.execute(
                text("SELECT COUNT(*) FROM fantasy_players")
            ).fetchone()[0]
            migration_log.append(f"Fantasy players inserted: {new_players_count}")
        else:
            migration_log.append("Fantasy players already exist, skipping...")

        if analytics_count == 0:
            migration_log.append("Inserting player analytics data...")
            for insert_sql in analytics_inserts:
                db.execute(text(insert_sql))
            db.commit()

            # Check new count
            new_analytics_count = db.execute(
                text("SELECT COUNT(*) FROM player_analytics")
            ).fetchone()[0]
            migration_log.append(f"Player analytics inserted: {new_analytics_count}")
        else:
            migration_log.append("Player analytics already exist, skipping...")

        # Final verification
        final_players = db.execute(
            text("SELECT COUNT(*) FROM fantasy_players")
        ).fetchone()[0]
        final_analytics = db.execute(
            text("SELECT COUNT(*) FROM player_analytics")
        ).fetchone()[0]

        migration_log.append(
            f"Migration complete - Players: {final_players}, Analytics: {final_analytics}"
        )

        # Test query to verify data linkage
        test_query = """
            SELECT fp.name, fp.position, fp.team, pa.week, pa.season, pa.ppr_points
            FROM fantasy_players fp
            JOIN player_analytics pa ON fp.platform_player_id::integer = pa.player_id
            ORDER BY fp.name, pa.week
            LIMIT 10
        """
        test_results = db.execute(text(test_query)).fetchall()
        sample_data = []
        for row in test_results:
            sample_data.append(
                {
                    "name": row[0],
                    "position": row[1],
                    "team": row[2],
                    "week": row[3],
                    "season": row[4],
                    "ppr_points": row[5],
                }
            )

        return {
            "success": True,
            "migration_log": migration_log,
            "final_counts": {
                "fantasy_players": final_players,
                "player_analytics": final_analytics,
            },
            "sample_data": sample_data,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    logger.info(
        f"🚀 Starting server on port {port} - {settings.ENVIRONMENT.upper()} mode"
    )
    uvicorn.run(app, host="0.0.0.0", port=port)
