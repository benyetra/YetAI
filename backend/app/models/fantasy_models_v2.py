"""
Simplified Fantasy Sports Models - V2 Schema
Streamlined design focusing on simplicity and scalability
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum
from datetime import datetime
from typing import Dict, List, Optional

# Enums for data validation
class FantasyPlatform(str, enum.Enum):
    SLEEPER = "sleeper"
    YAHOO = "yahoo"
    ESPN = "espn"

class LeagueStatus(str, enum.Enum):
    PRE_DRAFT = "pre_draft"
    DRAFTING = "drafting"
    IN_SEASON = "in_season"
    COMPLETE = "complete"

class ScoringType(str, enum.Enum):
    STANDARD = "standard"
    HALF_PPR = "half_ppr"
    PPR = "ppr"
    SUPER_FLEX = "super_flex"

class PlayerStatus(str, enum.Enum):
    ACTIVE = "active"
    INJURED = "injured"
    OUT = "out"
    DOUBTFUL = "doubtful"
    QUESTIONABLE = "questionable"
    BYE = "bye"
    INACTIVE = "inactive"

class TransactionType(str, enum.Enum):
    ADD = "add"
    DROP = "drop"
    TRADE = "trade"
    WAIVER = "waiver"
    FREE_AGENT = "free_agent"

# Core Tables - Simplified Schema

class League(Base):
    """
    Unified league table - works with any fantasy platform
    Replaces: SleeperLeague, FantasyLeague
    """
    __tablename__ = "leagues"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Platform info
    platform = Column(Enum(FantasyPlatform), nullable=False)
    external_league_id = Column(String(255), nullable=False)  # sleeper_league_id, yahoo_league_id, etc
    
    # League metadata
    name = Column(String(255), nullable=False)
    season = Column(Integer, nullable=False)
    current_week = Column(Integer, default=1)
    total_teams = Column(Integer, nullable=False)
    
    # League settings
    status = Column(Enum(LeagueStatus), default=LeagueStatus.PRE_DRAFT)
    scoring_type = Column(Enum(ScoringType), default=ScoringType.HALF_PPR)
    roster_positions = Column(JSON, default=list)  # ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K"]
    scoring_settings = Column(JSON, default=dict)  # Detailed scoring rules
    
    # Trading settings
    trade_deadline_week = Column(Integer, default=13)
    playoff_start_week = Column(Integer, default=15)
    playoff_teams = Column(Integer, default=6)
    
    # Sync tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)
    sync_enabled = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User")
    teams = relationship("Team", back_populates="league", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="league", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_league_platform_external', 'platform', 'external_league_id'),
        Index('idx_league_user_season', 'user_id', 'season'),
    )

class Team(Base):
    """
    Unified team/roster table
    Replaces: SleeperRoster, FantasyTeam
    """
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False, index=True)
    
    # External IDs
    external_team_id = Column(String(255), nullable=False)  # sleeper_roster_id, yahoo_team_id, etc
    external_owner_id = Column(String(255), nullable=False)  # sleeper_owner_id, yahoo_user_id, etc
    
    # Team info
    team_name = Column(String(255))
    owner_name = Column(String(255))
    avatar_url = Column(String(500))
    
    # Current season stats
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    points_for = Column(Float, default=0.0)
    points_against = Column(Float, default=0.0)
    
    # Current roster (JSON arrays for flexibility)
    active_players = Column(JSON, default=list)  # List of external_player_ids currently on roster
    starting_lineup = Column(JSON, default=list)  # List of external_player_ids in starting lineup
    bench_players = Column(JSON, default=list)  # List of external_player_ids on bench
    ir_players = Column(JSON, default=list)  # List of external_player_ids on IR
    
    # League position
    waiver_position = Column(Integer)
    playoff_seed = Column(Integer)
    
    # Sync tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("League", back_populates="teams")
    transactions = relationship("Transaction", back_populates="team", cascade="all, delete-orphan")
    
    # Computed properties for analytics
    @property
    def total_points(self) -> float:
        return self.points_for
    
    @property
    def win_percentage(self) -> float:
        total_games = self.wins + self.losses + self.ties
        return self.wins / total_games if total_games > 0 else 0.0
    
    @property
    def all_players(self) -> List[str]:
        """Get all player IDs on this team"""
        return list(set(self.active_players + self.bench_players + self.ir_players))
    
    # Indexes
    __table_args__ = (
        Index('idx_team_league_external', 'league_id', 'external_team_id'),
        Index('idx_team_owner', 'external_owner_id'),
    )

class Player(Base):
    """
    Unified player table with all necessary data for analytics
    Replaces: SleeperPlayer, FantasyPlayer
    """
    __tablename__ = "players"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # External IDs from different platforms
    sleeper_id = Column(String(255), index=True)
    yahoo_id = Column(String(255), index=True)
    espn_id = Column(String(255), index=True)
    
    # Basic info
    first_name = Column(String(100))
    last_name = Column(String(100))
    full_name = Column(String(255), index=True)
    position = Column(String(10), index=True)
    nfl_team = Column(String(10), index=True)
    
    # Physical attributes
    age = Column(Integer)
    height = Column(String(10))
    weight = Column(String(10))
    years_exp = Column(Integer)
    college = Column(String(255))
    
    # Current status
    status = Column(Enum(PlayerStatus), default=PlayerStatus.ACTIVE)
    injury_status = Column(String(50))
    injury_notes = Column(Text)
    
    # Fantasy relevance
    fantasy_positions = Column(JSON, default=list)  # ["RB", "FLEX"] for multi-position eligibility
    depth_chart_position = Column(Integer)
    depth_chart_order = Column(Integer)
    
    # Analytics data (for AI suggestions)
    season_stats = Column(JSON, default=dict)  # Current season stats
    recent_performance = Column(JSON, default=dict)  # Last 4 weeks performance
    matchup_data = Column(JSON, default=dict)  # Upcoming matchup analysis
    trade_value = Column(Float)  # Calculated trade value
    ownership_percentage = Column(Float)  # Roster % across leagues
    
    # News and updates
    news_updated = Column(DateTime)
    hashtag = Column(String(255))  # Social media hashtag
    
    # Sync tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    transactions = relationship("Transaction", back_populates="player")
    projections = relationship("WeeklyProjection", back_populates="player", cascade="all, delete-orphan")
    
    # Computed properties
    @property
    def display_name(self) -> str:
        return self.full_name or f"{self.first_name or ''} {self.last_name or ''}".strip() or f"Player {self.sleeper_id}"
    
    @property
    def is_injured(self) -> bool:
        return self.status in [PlayerStatus.INJURED, PlayerStatus.OUT, PlayerStatus.DOUBTFUL]
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_player_name_position', 'full_name', 'position'),
        Index('idx_player_team_position', 'nfl_team', 'position'),
        Index('idx_player_sleeper', 'sleeper_id'),
    )

class Transaction(Base):
    """
    Track all fantasy transactions for analytics and history
    Replaces: FantasyTransaction + trade tracking
    """
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)  # Null for complex trades
    
    # Transaction details
    transaction_type = Column(Enum(TransactionType), nullable=False)
    week = Column(Integer, nullable=False)
    
    # Transaction data (flexible JSON for different transaction types)
    transaction_data = Column(JSON, nullable=False)  # Contains all transaction details
    """
    Example transaction_data structures:
    
    ADD/DROP: {
        "added_player_id": "1234",
        "dropped_player_id": "5678",
        "waiver_priority": 3,
        "bid_amount": 15
    }
    
    TRADE: {
        "trade_id": "abc123",
        "teams": [
            {
                "team_id": 1,
                "gives": ["player_1", "player_2"],
                "receives": ["player_3", "player_4"]
            },
            {
                "team_id": 2, 
                "gives": ["player_3", "player_4"],
                "receives": ["player_1", "player_2"]
            }
        ],
        "draft_picks": [...],
        "trade_value_analysis": {...}
    }
    """
    
    # Status tracking
    status = Column(String(50), default="completed")  # completed, pending, failed, cancelled
    processed_at = Column(DateTime, default=datetime.utcnow)
    
    # Sync tracking
    external_transaction_id = Column(String(255))  # sleeper transaction ID, etc
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("League", back_populates="transactions")
    team = relationship("Team", back_populates="transactions")
    player = relationship("Player", back_populates="transactions")
    
    # Indexes
    __table_args__ = (
        Index('idx_transaction_league_week', 'league_id', 'week'),
        Index('idx_transaction_type_date', 'transaction_type', 'processed_at'),
    )

class WeeklyProjection(Base):
    """
    Store weekly projections and performance for AI analysis
    Replaces: PlayerProjection + adds actual performance tracking
    """
    __tablename__ = "weekly_projections"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    
    # Week info
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    
    # Projections (before the week)
    projected_points = Column(Float)
    projected_stats = Column(JSON, default=dict)  # Detailed projections
    projection_source = Column(String(100))  # "internal_ai", "sleeper", "fantasypros"
    confidence_score = Column(Float)  # 0-100 confidence in projection
    
    # Actual performance (after the week)
    actual_points = Column(Float)
    actual_stats = Column(JSON, default=dict)  # Detailed actual stats
    performance_grade = Column(String(10))  # A+, A, B+, B, C+, C, D, F
    
    # Matchup context
    opponent_team = Column(String(10))  # NFL team opponent
    home_away = Column(String(10))  # "home", "away"
    weather_conditions = Column(JSON, default=dict)
    injury_report = Column(String(255))
    
    # AI insights
    recommendation = Column(String(50))  # "start", "sit", "flex", "avoid"
    reasoning = Column(Text)  # AI explanation for recommendation
    risk_level = Column(String(20))  # "low", "medium", "high"
    
    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("Player", back_populates="projections")
    
    # Computed properties
    @property
    def accuracy_score(self) -> Optional[float]:
        """Calculate how accurate the projection was (0-100)"""
        if self.projected_points is None or self.actual_points is None:
            return None
        diff = abs(self.projected_points - self.actual_points)
        max_diff = max(self.projected_points, self.actual_points, 1)
        return max(0, 100 - (diff / max_diff * 100))
    
    # Indexes
    __table_args__ = (
        Index('idx_projection_player_week', 'player_id', 'season', 'week'),
        Index('idx_projection_week_recommendation', 'season', 'week', 'recommendation'),
    )

class TradeAnalysis(Base):
    """
    Store detailed trade analysis for AI learning and user insights
    New table for advanced trade analytics
    """
    __tablename__ = "trade_analyses"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False, index=True)
    
    # Trade participants
    team_ids = Column(JSON, nullable=False)  # List of team IDs involved
    
    # Trade details
    trade_data = Column(JSON, nullable=False)  # Complete trade breakdown
    """
    Example trade_data:
    {
        "teams": [
            {
                "team_id": 1,
                "gives": [
                    {"player_id": "1234", "player_name": "Player A", "position": "RB", "trade_value": 25.5},
                    {"draft_pick": "2024_round_2", "value": 8.0}
                ],
                "receives": [
                    {"player_id": "5678", "player_name": "Player B", "position": "WR", "trade_value": 28.2}
                ],
                "net_value": +2.7,
                "positional_impact": {"RB": -1, "WR": +1}
            }
        ]
    }
    """
    
    # AI Analysis
    overall_grade = Column(String(10))  # A+, A, B+, etc. for the trade overall
    fairness_score = Column(Float)  # 0-100, how fair the trade is
    winner_team_id = Column(Integer)  # Which team "won" the trade
    
    # Detailed analysis
    value_analysis = Column(JSON)  # Detailed value breakdown
    positional_analysis = Column(JSON)  # How it affects each team's positions
    league_context_analysis = Column(JSON)  # Playoff implications, standings impact
    
    # AI reasoning
    ai_summary = Column(Text)  # Natural language summary
    risk_factors = Column(JSON, default=list)  # List of risks for each team
    
    # Outcome tracking (filled in later)
    outcome_grade = Column(String(10))  # How did the trade work out? (A+, A, B+, etc.)
    outcome_notes = Column(Text)  # Notes on how the trade worked out
    
    # Tracking
    trade_date = Column(DateTime, nullable=False)
    analysis_date = Column(DateTime, default=datetime.utcnow)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    
    # Relationships
    league = relationship("League")
    
    # Indexes
    __table_args__ = (
        Index('idx_trade_league_date', 'league_id', 'trade_date'),
        Index('idx_trade_season_week', 'season', 'week'),
    )