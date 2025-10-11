"""
SQLAlchemy database models for persistent storage
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
    Enum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
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


class GameStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ELITE = "elite"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    subscription_tier = Column(Enum(SubscriptionTier), default=SubscriptionTier.FREE)
    subscription_expires_at = Column(DateTime)
    subscription_status = Column(String(50))  # active, canceled, past_due, etc.
    subscription_current_period_end = Column(DateTime)
    stripe_customer_id = Column(String(255))
    stripe_subscription_id = Column(String(255))
    favorite_teams = Column(JSON, default=list)
    preferred_sports = Column(JSON, default=list)
    notification_settings = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String(255))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

    # 2FA fields
    totp_enabled = Column(Boolean, default=False)
    totp_secret = Column(String(255))
    backup_codes = Column(JSON, default=list)
    totp_last_used = Column(DateTime)

    # Temporary 2FA setup fields
    temp_totp_secret = Column(String(255))
    temp_backup_codes = Column(JSON, default=list)

    # Avatar fields
    avatar_url = Column(String(500))
    avatar_thumbnail = Column(String(500))

    # Password reset fields
    reset_token = Column(String(255))
    reset_token_expires = Column(DateTime)

    # Fantasy platform fields
    sleeper_user_id = Column(String(255))  # Sleeper platform user ID

    # Relationships
    bets = relationship("Bet", back_populates="user", cascade="all, delete-orphan")
    parlay_bets = relationship(
        "ParlayBet", back_populates="user", cascade="all, delete-orphan"
    )
    shared_bets = relationship(
        "SharedBet", back_populates="user", cascade="all, delete-orphan"
    )
    yetai_bets = relationship(
        "YetAIBet", back_populates="user", cascade="all, delete-orphan"
    )
    live_bets = relationship(
        "LiveBet", back_populates="user", cascade="all, delete-orphan"
    )


class Game(Base):
    __tablename__ = "games"

    id = Column(String(255), primary_key=True, index=True)  # External API game ID
    sport_key = Column(String(100), nullable=False)
    sport_title = Column(String(100), nullable=False)
    home_team = Column(String(255), nullable=False)
    away_team = Column(String(255), nullable=False)
    commence_time = Column(DateTime, nullable=False)
    status = Column(Enum(GameStatus), default=GameStatus.SCHEDULED)
    home_score = Column(Integer, default=0)
    away_score = Column(Integer, default=0)
    last_update = Column(DateTime, default=datetime.utcnow)

    # Game metadata
    venue = Column(String(255))
    weather = Column(JSON)
    odds_data = Column(JSON)  # Store latest odds from Odds API
    broadcast_info = Column(JSON)  # Store broadcast data from ESPN API
    is_nationally_televised = Column(Boolean, default=False)

    # Relationships
    bets = relationship("Bet", back_populates="game")


class Bet(Base):
    __tablename__ = "bets"

    id = Column(String(255), primary_key=True, index=True)  # UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(String(255), ForeignKey("games.id"), nullable=True)
    parlay_id = Column(String(255), ForeignKey("parlay_bets.id"), nullable=True)

    bet_type = Column(Enum(BetType), nullable=False)
    selection = Column(String(255), nullable=False)
    odds = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    potential_win = Column(Float, nullable=False)
    status = Column(Enum(BetStatus), default=BetStatus.PENDING)

    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime)
    result_amount = Column(Float)

    # Game details for display (cached from game)
    home_team = Column(String(255))
    away_team = Column(String(255))
    sport = Column(String(100))
    commence_time = Column(DateTime)

    # Bet metadata
    bookmaker = Column(String(100))
    line_value = Column(Float)  # For spread/total bets

    # Relationships
    user = relationship("User", back_populates="bets")
    game = relationship("Game", back_populates="bets")
    parlay = relationship("ParlayBet", back_populates="legs")


class ParlayBet(Base):
    __tablename__ = "parlay_bets"

    id = Column(String(255), primary_key=True, index=True)  # UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    amount = Column(Float, nullable=False)
    total_odds = Column(Float, nullable=False)
    potential_win = Column(Float, nullable=False)
    status = Column(Enum(BetStatus), default=BetStatus.PENDING)

    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime)
    result_amount = Column(Float)

    leg_count = Column(Integer, nullable=False)

    # Relationships
    user = relationship("User", back_populates="parlay_bets")
    legs = relationship("Bet", back_populates="parlay", cascade="all, delete-orphan")


class SharedBet(Base):
    __tablename__ = "shared_bets"

    id = Column(String(255), primary_key=True, index=True)  # Short UUID for sharing
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    bet_id = Column(String(255), nullable=True)  # Reference to bet or parlay
    parlay_id = Column(String(255), nullable=True)

    # Cached bet data for sharing
    bet_data = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    views = Column(Integer, default=0)
    is_public = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="shared_bets")


class YetAIBet(Base):
    __tablename__ = "yetai_bets"

    id = Column(String(255), primary_key=True, index=True)  # UUID
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=True
    )  # null for admin-created
    game_id = Column(String(255), ForeignKey("games.id"), nullable=True)

    title = Column(String(255), nullable=False)
    description = Column(Text)
    bet_type = Column(Enum(BetType), nullable=False)
    selection = Column(String(255), nullable=False)
    odds = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)  # AI confidence score 0-100

    status = Column(String(50), default="active")  # active, settled, cancelled
    tier_requirement = Column(Enum(SubscriptionTier), default=SubscriptionTier.FREE)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    settled_at = Column(DateTime)
    result = Column(String(50))  # won, lost, push

    # AI metadata
    model_version = Column(String(100))
    prediction_factors = Column(JSON)  # Store AI reasoning
    historical_accuracy = Column(Float)
    parlay_legs = Column(JSON)  # For parlay bets, stores the leg details

    # Game details
    home_team = Column(String(255))
    away_team = Column(String(255))
    sport = Column(String(100))
    commence_time = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="yetai_bets")
    game = relationship("Game")


class LiveBet(Base):
    __tablename__ = "live_bets"

    id = Column(String(255), primary_key=True, index=True)  # UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    game_id = Column(
        String(255), nullable=False
    )  # Removed FK constraint for API-sourced games

    bet_type = Column(Enum(BetType), nullable=False)
    selection = Column(String(255), nullable=False)
    odds = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    potential_win = Column(Float, nullable=False)
    status = Column(Enum(BetStatus), default=BetStatus.LIVE)

    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime)
    result_amount = Column(Float)

    # Live betting specific fields
    game_time = Column(String(50))  # Quarter, inning, etc.
    current_score = Column(String(50))  # Score when bet was placed

    # Cash out tracking
    cash_out_available = Column(Boolean, default=True)
    cash_out_value = Column(Float)
    cashed_out_at = Column(DateTime)
    cash_out_amount = Column(Float)

    # Game details (cached)
    home_team = Column(String(255))
    away_team = Column(String(255))
    sport = Column(String(100))
    commence_time = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="live_bets")


# Additional tables for advanced features
class BetLimit(Base):
    __tablename__ = "bet_limits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    daily_limit = Column(Float, default=5000)
    weekly_limit = Column(Float, default=20000)
    single_bet_limit = Column(Float, default=10000)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BetHistory(Base):
    __tablename__ = "bet_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    bet_id = Column(String(255), nullable=False)

    action = Column(
        String(50), nullable=False
    )  # placed, settled, cancelled, cashed_out
    old_status = Column(String(50))
    new_status = Column(String(50))
    amount = Column(Float)

    timestamp = Column(DateTime, default=datetime.utcnow)
    bet_metadata = Column(JSON)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    user_agent = Column(Text)
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)


# Fantasy Sports Tables


class SleeperLeague(Base):
    __tablename__ = "sleeper_leagues"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sleeper_league_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    season = Column(Integer, nullable=False)
    total_rosters = Column(Integer, nullable=False)
    status = Column(String(50))  # pre_draft, drafting, in_season, complete
    scoring_type = Column(String(50))  # ppr, half_ppr, standard
    roster_positions = Column(JSON)
    scoring_settings = Column(JSON)
    waiver_settings = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")
    rosters = relationship(
        "SleeperRoster", back_populates="league", cascade="all, delete-orphan"
    )


class SleeperRoster(Base):
    __tablename__ = "sleeper_rosters"

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("sleeper_leagues.id"), nullable=False)
    sleeper_roster_id = Column(String(255), nullable=False)
    sleeper_owner_id = Column(String(255), nullable=False)
    team_name = Column(String(255))
    owner_name = Column(String(255))
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    points_for = Column(Float, default=0)
    points_against = Column(Float, default=0)
    waiver_position = Column(Integer)
    players = Column(JSON, default=list)  # List of sleeper_player_ids
    starters = Column(JSON, default=list)  # Current week starters
    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)

    # Relationships
    league = relationship("SleeperLeague", back_populates="rosters")


class SleeperPlayer(Base):
    __tablename__ = "sleeper_players"

    id = Column(Integer, primary_key=True, index=True)
    sleeper_player_id = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    full_name = Column(String(255))
    position = Column(String(10))
    team = Column(String(10))
    age = Column(Integer)
    height = Column(String(10))
    weight = Column(String(10))
    years_exp = Column(Integer)
    college = Column(String(255))
    fantasy_positions = Column(JSON, default=list)
    status = Column(String(50))  # Active, Inactive, etc.
    injury_status = Column(String(50))
    depth_chart_position = Column(Integer)
    depth_chart_order = Column(Integer)
    search_rank = Column(Integer)
    hashtag = Column(String(255))

    # External IDs
    espn_id = Column(String(50))
    yahoo_id = Column(String(50))
    fantasy_data_id = Column(String(50))
    rotoworld_id = Column(String(50))
    rotowire_id = Column(String(50))
    sportradar_id = Column(String(50))
    stats_id = Column(String(50))

    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)
