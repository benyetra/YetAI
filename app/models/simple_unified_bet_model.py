"""
Simple Unified Bet Model - No foreign key constraints for initial migration

This simplified model removes foreign key constraints to allow easy migration.
Referential integrity will be maintained at the application level.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    JSON,
    Enum,
)
from app.core.database import Base
import enum
from datetime import datetime


class BetStatus(str, enum.Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    PUSHED = "pushed"
    CANCELLED = "cancelled"
    LIVE = "live"
    CASHED_OUT = "cashed_out"


class BetType(str, enum.Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PARLAY = "parlay"
    PROP = "prop"


class BetSource(str, enum.Enum):
    STRAIGHT = "straight"
    LIVE = "live"
    PREDICTIONS = "predictions"
    PARLAYS = "parlays"
    ADMIN = "admin"


class GameStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    COMPLETED = "completed"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class TeamSide(str, enum.Enum):
    HOME = "home"
    AWAY = "away"
    NONE = "none"


class OverUnder(str, enum.Enum):
    OVER = "over"
    UNDER = "under"
    NONE = "none"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ELITE = "elite"


class SimpleUnifiedBet(Base):
    __tablename__ = "simple_unified_bets"

    # === CORE BET IDENTIFICATION ===
    id = Column(String(255), primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)

    # === ODDS API EVENT IDENTIFICATION ===
    odds_api_event_id = Column(String(255), nullable=False, index=True)
    game_id = Column(String(255), nullable=True)  # No FK constraint

    # === BET FUNDAMENTALS ===
    bet_type = Column(Enum(BetType), nullable=False)
    amount = Column(Float, nullable=False)
    odds = Column(Float, nullable=False)
    potential_win = Column(Float, nullable=False)
    status = Column(Enum(BetStatus), default=BetStatus.PENDING)

    # === DETAILED BET SELECTION DATA ===
    selection = Column(String(500), nullable=False)
    team_selection = Column(Enum(TeamSide), default=TeamSide.NONE)
    selected_team_name = Column(String(255))

    # Spread bet details
    spread_value = Column(Float)
    spread_selection = Column(Enum(TeamSide), default=TeamSide.NONE)

    # Total bet details
    total_points = Column(Float)
    over_under_selection = Column(Enum(OverUnder), default=OverUnder.NONE)

    # === GAME CONTEXT AT BET PLACEMENT ===
    home_team = Column(String(255), nullable=False)
    away_team = Column(String(255), nullable=False)
    sport = Column(String(100), nullable=False)
    commence_time = Column(DateTime, nullable=False)
    game_status_at_placement = Column(Enum(GameStatus), default=GameStatus.SCHEDULED)

    # === TIMING ===
    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime)
    expires_at = Column(DateTime)

    # === RESULTS ===
    result_amount = Column(Float)
    reasoning = Column(Text)

    # Game outcome data
    final_home_score = Column(Integer)
    final_away_score = Column(Integer)
    final_total_score = Column(Integer)
    game_completed_at = Column(DateTime)

    # === ODDS API DATA PRESERVATION ===
    bookmaker = Column(String(100), nullable=False, default="fanduel")
    original_odds_data = Column(JSON)

    # === BET SOURCE & CONTEXT ===
    source = Column(Enum(BetSource), nullable=False, default=BetSource.STRAIGHT)
    line_value = Column(Float)

    # === PARLAY SUPPORT ===
    is_parlay = Column(Boolean, default=False)
    parent_bet_id = Column(String(255), nullable=True)  # No FK constraint
    leg_count = Column(Integer, default=1)
    leg_position = Column(Integer, default=1)
    total_odds = Column(Float)
    parlay_legs = Column(JSON)

    # === LIVE BETTING SUPPORT ===
    is_live = Column(Boolean, default=False)
    game_time_at_placement = Column(String(50))
    score_at_placement = Column(String(50))

    # Cash out functionality
    cash_out_available = Column(Boolean, default=False)
    cash_out_value = Column(Float)
    cashed_out_at = Column(DateTime)
    cash_out_amount = Column(Float)

    # === YETAI BET SUPPORT ===
    is_yetai_bet = Column(Boolean, default=False)
    title = Column(String(255))
    description = Column(Text)
    confidence = Column(Float)
    tier_requirement = Column(Enum(SubscriptionTier), default=SubscriptionTier.FREE)

    # AI metadata
    model_version = Column(String(100))
    prediction_factors = Column(JSON)
    historical_accuracy = Column(Float)

    # === ANALYTICS & TRACKING ===
    sport_season = Column(String(50))
    venue = Column(String(255))
    weather_conditions = Column(JSON)

    # Odds movement tracking
    opening_odds = Column(Float)
    closing_odds = Column(Float)
    odds_movement = Column(Float)

    # Bet timing analysis
    hours_before_game = Column(Float)

    # Performance tracking
    expected_value = Column(Float)
    actual_return = Column(Float)

    # === SHARING & SOCIAL ===
    is_shared = Column(Boolean, default=False)
    share_id = Column(String(50))
    share_expires_at = Column(DateTime)
    share_views = Column(Integer, default=0)

    # === METADATA & EXTENSIBILITY ===
    bet_metadata = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    notes = Column(Text)

    # === AUDIT TRAIL ===
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
