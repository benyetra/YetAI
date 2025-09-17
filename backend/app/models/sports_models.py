"""
Database models for sports data and odds information.

These models represent the structure of sports data stored in the database,
including games, odds, bookmakers, and scores.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    JSON,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from enum import Enum

Base = declarative_base()


class SportCategory(str, Enum):
    """Sport category enumeration"""

    FOOTBALL = "Football"
    BASKETBALL = "Basketball"
    BASEBALL = "Baseball"
    HOCKEY = "Hockey"
    SOCCER = "Soccer"
    TENNIS = "Tennis"
    GOLF = "Golf"
    COMBAT_SPORTS = "Combat Sports"
    OTHER = "Other"


class GameStatus(str, Enum):
    """Game status enumeration"""

    SCHEDULED = "scheduled"
    LIVE = "live"
    COMPLETED = "completed"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class MarketType(str, Enum):
    """Betting market types"""

    H2H = "h2h"  # Head to head (moneyline)
    SPREADS = "spreads"  # Point spreads
    TOTALS = "totals"  # Over/under totals


# SQLAlchemy Database Models


class Sport(Base):
    """Sport information table"""

    __tablename__ = "sports"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(50), default=SportCategory.OTHER)
    active = Column(Boolean, default=True)
    has_outrights = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    games = relationship("Game", back_populates="sport")


class Game(Base):
    """Game/match information table"""

    __tablename__ = "games"

    id = Column(String(100), primary_key=True, index=True)  # External API ID
    sport_id = Column(Integer, ForeignKey("sports.id"), nullable=False)
    sport_key = Column(String(100), nullable=False, index=True)
    sport_title = Column(String(200), nullable=False)
    home_team = Column(String(200), nullable=False)
    away_team = Column(String(200), nullable=False)
    commence_time = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(20), default=GameStatus.SCHEDULED, index=True)
    home_score = Column(Integer)
    away_score = Column(Integer)
    completed = Column(Boolean, default=False)
    last_odds_update = Column(DateTime(timezone=True))
    last_score_update = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    sport = relationship("Sport", back_populates="games")
    odds = relationship("GameOdds", back_populates="game")
    bookmaker_odds = relationship("BookmakerOdds", back_populates="game")


class Bookmaker(Base):
    """Bookmaker information table"""

    __tablename__ = "bookmakers"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    odds = relationship("BookmakerOdds", back_populates="bookmaker")


class GameOdds(Base):
    """Aggregated odds for a game (best odds across bookmakers)"""

    __tablename__ = "game_odds"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(String(100), ForeignKey("games.id"), nullable=False)
    market_type = Column(String(20), nullable=False)  # h2h, spreads, totals

    # Moneyline odds
    home_moneyline = Column(Float)
    away_moneyline = Column(Float)

    # Spread odds
    home_spread = Column(Float)
    home_spread_odds = Column(Float)
    away_spread = Column(Float)
    away_spread_odds = Column(Float)

    # Totals odds
    total_points = Column(Float)
    over_odds = Column(Float)
    under_odds = Column(Float)

    last_update = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    game = relationship("Game", back_populates="odds")


class BookmakerOdds(Base):
    """Detailed odds from specific bookmakers"""

    __tablename__ = "bookmaker_odds"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(String(100), ForeignKey("games.id"), nullable=False)
    bookmaker_id = Column(Integer, ForeignKey("bookmakers.id"), nullable=False)
    market_type = Column(String(20), nullable=False)  # h2h, spreads, totals

    # Raw odds data as JSON
    odds_data = Column(JSON)  # Store the full market data from API

    # Parsed odds for quick access
    home_moneyline = Column(Float)
    away_moneyline = Column(Float)
    home_spread = Column(Float)
    home_spread_odds = Column(Float)
    away_spread = Column(Float)
    away_spread_odds = Column(Float)
    total_points = Column(Float)
    over_odds = Column(Float)
    under_odds = Column(Float)

    last_update = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    game = relationship("Game", back_populates="bookmaker_odds")
    bookmaker = relationship("Bookmaker", back_populates="odds")


class OddsHistory(Base):
    """Historical odds data for analysis"""

    __tablename__ = "odds_history"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(String(100), ForeignKey("games.id"), nullable=False)
    bookmaker_id = Column(Integer, ForeignKey("bookmakers.id"))
    market_type = Column(String(20), nullable=False)

    # Snapshot of odds at this time
    odds_snapshot = Column(JSON)  # Full odds data

    # Key values for analysis
    home_moneyline = Column(Float)
    away_moneyline = Column(Float)
    home_spread = Column(Float)
    away_spread = Column(Float)
    total_points = Column(Float)

    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# Pydantic Models for API responses


class SportResponse(BaseModel):
    """Sport response model"""

    id: Optional[int]
    key: str
    title: str
    description: Optional[str]
    category: str
    active: bool
    has_outrights: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class GameResponse(BaseModel):
    """Game response model"""

    id: str
    sport_key: str
    sport_title: str
    home_team: str
    away_team: str
    commence_time: datetime
    status: str
    home_score: Optional[int]
    away_score: Optional[int]
    completed: bool
    last_odds_update: Optional[datetime]
    last_score_update: Optional[datetime]

    class Config:
        from_attributes = True


class BookmakerResponse(BaseModel):
    """Bookmaker response model"""

    id: Optional[int]
    key: str
    title: str
    active: bool

    class Config:
        from_attributes = True


class OddsResponse(BaseModel):
    """Odds response model"""

    id: Optional[int]
    game_id: str
    market_type: str
    home_moneyline: Optional[float]
    away_moneyline: Optional[float]
    home_spread: Optional[float]
    home_spread_odds: Optional[float]
    away_spread: Optional[float]
    away_spread_odds: Optional[float]
    total_points: Optional[float]
    over_odds: Optional[float]
    under_odds: Optional[float]
    last_update: datetime

    class Config:
        from_attributes = True


class BookmakerOddsResponse(BaseModel):
    """Bookmaker-specific odds response model"""

    id: Optional[int]
    game_id: str
    bookmaker: BookmakerResponse
    market_type: str
    odds_data: Dict[str, Any]
    home_moneyline: Optional[float]
    away_moneyline: Optional[float]
    home_spread: Optional[float]
    home_spread_odds: Optional[float]
    away_spread: Optional[float]
    away_spread_odds: Optional[float]
    total_points: Optional[float]
    over_odds: Optional[float]
    under_odds: Optional[float]
    last_update: datetime

    class Config:
        from_attributes = True


class GameWithOdds(BaseModel):
    """Game with associated odds"""

    game: GameResponse
    best_odds: List[OddsResponse]
    bookmaker_odds: List[BookmakerOddsResponse]

    class Config:
        from_attributes = True


# Pydantic models for database operations


class SportCreate(BaseModel):
    """Model for creating a sport"""

    key: str
    title: str
    description: Optional[str] = None
    category: str = SportCategory.OTHER
    active: bool = True
    has_outrights: bool = False


class SportUpdate(BaseModel):
    """Model for updating a sport"""

    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    active: Optional[bool] = None
    has_outrights: Optional[bool] = None


class GameCreate(BaseModel):
    """Model for creating a game"""

    id: str
    sport_key: str
    sport_title: str
    home_team: str
    away_team: str
    commence_time: datetime
    status: str = GameStatus.SCHEDULED


class GameUpdate(BaseModel):
    """Model for updating a game"""

    home_team: Optional[str] = None
    away_team: Optional[str] = None
    commence_time: Optional[datetime] = None
    status: Optional[str] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    completed: Optional[bool] = None


class BookmakerCreate(BaseModel):
    """Model for creating a bookmaker"""

    key: str
    title: str
    active: bool = True


class OddsCreate(BaseModel):
    """Model for creating odds"""

    game_id: str
    market_type: str
    home_moneyline: Optional[float] = None
    away_moneyline: Optional[float] = None
    home_spread: Optional[float] = None
    home_spread_odds: Optional[float] = None
    away_spread: Optional[float] = None
    away_spread_odds: Optional[float] = None
    total_points: Optional[float] = None
    over_odds: Optional[float] = None
    under_odds: Optional[float] = None


class BookmakerOddsCreate(BaseModel):
    """Model for creating bookmaker-specific odds"""

    game_id: str
    bookmaker_key: str
    market_type: str
    odds_data: Dict[str, Any]
    home_moneyline: Optional[float] = None
    away_moneyline: Optional[float] = None
    home_spread: Optional[float] = None
    home_spread_odds: Optional[float] = None
    away_spread: Optional[float] = None
    away_spread_odds: Optional[float] = None
    total_points: Optional[float] = None
    over_odds: Optional[float] = None
    under_odds: Optional[float] = None
    last_update: datetime
