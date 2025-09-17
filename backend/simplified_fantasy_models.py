"""
Simplified Fantasy Database Models

New Structure:
User (primary)
  -> sleeper_user_id (stored directly on User table)
  -> Leagues (one-to-many)
    -> season (year)
    -> Teams (one-to-many)
      -> is_user_team (boolean to identify which team belongs to the user)
      -> Players (many-to-many through RosterSpots)

This eliminates the need for:
- FantasyUser (redundant)
- Multiple league records for same platform_league_id
- Complex ownership chains
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
    Table,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum
from datetime import datetime


class FantasyPlatform(str, enum.Enum):
    SLEEPER = "sleeper"
    ESPN = "espn"
    YAHOO = "yahoo"


class FantasyPosition(str, enum.Enum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DEF = "DEF"
    FLEX = "FLEX"
    BENCH = "BENCH"


class LeagueStatus(str, enum.Enum):
    PRE_DRAFT = "pre_draft"
    DRAFTING = "drafting"
    IN_SEASON = "in_season"
    COMPLETE = "complete"


class ScoringType(str, enum.Enum):
    STANDARD = "standard"
    PPR = "ppr"
    HALF_PPR = "half_ppr"


# Updated User model (extend existing User table)
# Add these fields to existing User model:
# sleeper_user_id = Column(String(255))  # Direct Sleeper user ID
# sleeper_username = Column(String(255))  # Sleeper display name


class League(Base):
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Platform info
    platform = Column(Enum(FantasyPlatform), default=FantasyPlatform.SLEEPER)
    platform_league_id = Column(
        String(255), nullable=False, index=True
    )  # Sleeper league ID

    # League details
    name = Column(String(255), nullable=False)
    season = Column(Integer, nullable=False, index=True)  # 2025, 2024, etc.
    status = Column(Enum(LeagueStatus), default=LeagueStatus.IN_SEASON)
    scoring_type = Column(Enum(ScoringType), default=ScoringType.HALF_PPR)

    # League settings
    total_teams = Column(Integer, default=12)
    roster_positions = Column(
        JSON
    )  # ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BENCH"...]
    scoring_settings = Column(JSON)

    # Sync info
    last_synced = Column(DateTime, default=datetime.utcnow)
    sync_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="leagues")
    teams = relationship("Team", back_populates="league", cascade="all, delete-orphan")

    # Unique constraint to prevent duplicate leagues per user per season
    __table_args__ = {"extend_existing": True}


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False, index=True)

    # Platform info
    platform_team_id = Column(
        String(255), nullable=False
    )  # Sleeper roster ID (1, 2, 3...)
    platform_owner_id = Column(String(255))  # Sleeper owner ID

    # Team details
    name = Column(String(255), nullable=False)
    owner_name = Column(String(255))
    is_user_team = Column(
        Boolean, default=False, index=True
    )  # TRUE for the authenticated user's team

    # Season stats
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    points_for = Column(Float, default=0.0)
    points_against = Column(Float, default=0.0)
    waiver_position = Column(Integer)
    playoff_seed = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    league = relationship("League", back_populates="teams")
    roster_spots = relationship(
        "RosterSpot", back_populates="team", cascade="all, delete-orphan"
    )


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)

    # Platform info
    platform = Column(Enum(FantasyPlatform), default=FantasyPlatform.SLEEPER)
    platform_player_id = Column(
        String(255), nullable=False, unique=True, index=True
    )  # Sleeper player ID

    # Player details
    name = Column(String(255), nullable=False, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    position = Column(Enum(FantasyPosition), nullable=False, index=True)
    team = Column(String(10), index=True)  # NFL team (e.g., "KC", "SF")

    # Additional info
    age = Column(Integer)
    height = Column(String(10))
    weight = Column(String(10))
    college = Column(String(255))
    years_exp = Column(Integer)

    # Status
    status = Column(String(50), default="Active")  # Active, Inactive, IR, etc.
    injury_status = Column(String(50))  # Healthy, Questionable, Out, etc.

    # External IDs for data enrichment
    espn_id = Column(String(50))
    yahoo_id = Column(String(50))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    roster_spots = relationship("RosterSpot", back_populates="player")


class RosterSpot(Base):
    __tablename__ = "roster_spots"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)

    # Roster info
    position = Column(Enum(FantasyPosition), nullable=False)
    week = Column(Integer, default=1)  # Current NFL week
    is_starter = Column(Boolean, default=False)  # In starting lineup vs bench

    # Performance
    points_scored = Column(Float, default=0.0)
    projected_points = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", back_populates="roster_spots")
    player = relationship("Player", back_populates="roster_spots")

    # Unique constraint: one player per team per week
    __table_args__ = {"extend_existing": True}


# Optional: Trade history and analysis tables (can be added later)
class TradeProposal(Base):
    __tablename__ = "trade_proposals"

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)

    # Trade details
    proposing_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    receiving_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    # Players/picks being traded
    proposed_players = Column(JSON)  # List of player IDs from proposing team
    requested_players = Column(JSON)  # List of player IDs from receiving team

    # Trade analysis
    fairness_score = Column(Float)  # AI-calculated fairness (0-100)
    analysis = Column(Text)  # AI trade analysis

    status = Column(
        String(50), default="pending"
    )  # pending, accepted, rejected, expired

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

    # Relationships
    league = relationship("League")
    proposing_team = relationship("Team", foreign_keys=[proposing_team_id])
    receiving_team = relationship("Team", foreign_keys=[receiving_team_id])
