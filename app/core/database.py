from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import settings
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine (with graceful fallback for missing DATABASE_URL)
try:
    engine = create_engine(
        settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=300, echo=settings.DEBUG
    )
    logger.info(f"Database engine created with URL: {settings.DATABASE_URL[:30]}...")
except Exception as e:
    logger.warning(f"Failed to create database engine: {e}")
    # Create a dummy engine that will fail gracefully when used
    engine = None

# Create SessionLocal class
if engine is not None:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    SessionLocal = None

# Create Base class for declarative models
Base = declarative_base()


def get_db():
    """Dependency to get database session"""
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not available")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    if engine is None:
        logger.warning("Database engine not available, skipping table creation")
        return False

    try:
        # Import all models to ensure they are registered
        from app.models.database_models import (
            User,
            Bet,
            ParlayBet,
            SharedBet,
            YetAIBet,
            LiveBet,
            Game,
        )
        from app.models.fantasy_models import (
            FantasyUser,
            FantasyLeague,
            FantasyTeam,
            FantasyPlayer,
            FantasyRosterSpot,
            PlayerProjection,
            FantasyRecommendation,
            FantasyMatchup,
            FantasyTransaction,
            WaiverWireTarget,
        )

        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        return True

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False


def check_db_connection():
    """Check if database connection is working"""
    if SessionLocal is None:
        logger.warning("Database not available")
        return False

    try:
        from sqlalchemy import text

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
