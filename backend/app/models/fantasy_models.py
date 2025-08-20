"""
SQLAlchemy models for Fantasy Sports integration
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum
from datetime import datetime

class FantasyPlatform(str, enum.Enum):
    SLEEPER = "sleeper"
    YAHOO = "yahoo"
    ESPN = "espn"

class FantasyLeagueType(str, enum.Enum):
    REDRAFT = "redraft"
    KEEPER = "keeper"
    DYNASTY = "dynasty"

class FantasyPosition(str, enum.Enum):
    QB = "QB"
    RB = "RB" 
    WR = "WR"
    TE = "TE"
    K = "K"
    DEF = "DEF"
    FLEX = "FLEX"
    SUPER_FLEX = "SUPER_FLEX"
    BENCH = "BENCH"
    IR = "IR"

class PlayerStatus(str, enum.Enum):
    ACTIVE = "active"
    INJURED = "injured"
    OUT = "out"
    DOUBTFUL = "doubtful"
    QUESTIONABLE = "questionable"
    PROBABLE = "probable"
    BYE = "bye"

class TransactionType(str, enum.Enum):
    ADD = "add"
    DROP = "drop"
    TRADE = "trade"
    WAIVER = "waiver"

class RecommendationType(str, enum.Enum):
    START_SIT = "start_sit"
    WAIVER_WIRE = "waiver_wire"
    TRADE = "trade"

class FantasyUser(Base):
    """Links platform user accounts to YetAI users"""
    __tablename__ = "fantasy_users"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform = Column(Enum(FantasyPlatform), nullable=False)
    platform_user_id = Column(String(255), nullable=False)
    platform_username = Column(String(255))
    
    # Platform-specific auth data
    access_token = Column(Text)  # For OAuth platforms
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)
    
    # Connection status
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    sync_error = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User")
    leagues = relationship("FantasyLeague", back_populates="fantasy_user")

class FantasyLeague(Base):
    """Fantasy league information"""
    __tablename__ = "fantasy_leagues"
    
    id = Column(Integer, primary_key=True, index=True)
    fantasy_user_id = Column(Integer, ForeignKey("fantasy_users.id"), nullable=False)
    platform = Column(Enum(FantasyPlatform), nullable=False)
    platform_league_id = Column(String(255), nullable=False)
    
    # League details
    name = Column(String(255), nullable=False)
    league_type = Column(Enum(FantasyLeagueType), default=FantasyLeagueType.REDRAFT)
    sport = Column(String(50), default="nfl")
    season = Column(Integer, nullable=False)
    
    # League settings
    team_count = Column(Integer)
    scoring_type = Column(String(50))  # standard, ppr, half_ppr, etc.
    roster_size = Column(Integer)
    playoff_teams = Column(Integer)
    trade_deadline = Column(DateTime)
    
    # Waiver settings
    waiver_type = Column(String(50))  # "FAAB", "waiver_priority", "free_agent"
    waiver_budget = Column(Integer)  # FAAB budget for the season
    waiver_clear_days = Column(Integer)  # Days on waivers
    
    # League configuration
    roster_positions = Column(JSON)  # Position slots configuration
    
    # Sync settings
    is_synced = Column(Boolean, default=True)
    sync_enabled = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    fantasy_user = relationship("FantasyUser", back_populates="leagues")
    teams = relationship("FantasyTeam", back_populates="league")
    matchups = relationship("FantasyMatchup", back_populates="league")

class FantasyTeam(Base):
    """Fantasy team within a league"""
    __tablename__ = "fantasy_teams"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    platform_team_id = Column(String(255), nullable=False)
    
    # Team details
    name = Column(String(255), nullable=False)
    owner_name = Column(String(255))
    is_user_team = Column(Boolean, default=False)  # True if this is the connected user's team
    
    # Team stats
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    points_for = Column(Float, default=0)
    points_against = Column(Float, default=0)
    
    # Waiver and standings
    waiver_position = Column(Integer)
    playoff_seed = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague", back_populates="teams")
    roster_spots = relationship("FantasyRosterSpot", back_populates="team")

class FantasyPlayer(Base):
    """Fantasy player information"""
    __tablename__ = "fantasy_players"
    
    id = Column(Integer, primary_key=True, index=True)
    platform = Column(Enum(FantasyPlatform), nullable=False)
    platform_player_id = Column(String(255), nullable=False)
    
    # Player details
    name = Column(String(255), nullable=False)
    position = Column(Enum(FantasyPosition), nullable=False)
    team = Column(String(10))  # NFL team abbreviation
    jersey_number = Column(String(5))
    
    # Player metadata
    age = Column(Integer)
    height = Column(String(10))
    weight = Column(Integer)
    college = Column(String(255))
    experience = Column(Integer)  # Years in league
    
    # Status
    status = Column(Enum(PlayerStatus), default=PlayerStatus.ACTIVE)
    injury_description = Column(String(500))
    
    # Fantasy metrics (updated regularly)
    adp = Column(Float)  # Average draft position
    ownership_percentage = Column(Float)
    add_percentage = Column(Float)  # Weekly add percentage
    drop_percentage = Column(Float)  # Weekly drop percentage
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    roster_spots = relationship("FantasyRosterSpot", back_populates="player")
    projections = relationship("PlayerProjection", back_populates="player")

class FantasyRosterSpot(Base):
    """Player roster spots on fantasy teams"""
    __tablename__ = "fantasy_roster_spots"
    
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    position = Column(Enum(FantasyPosition), nullable=False)
    week = Column(Integer)  # NFL week, null for season-long
    is_starter = Column(Boolean, default=False)
    
    # Performance tracking
    points_scored = Column(Float, default=0)
    projected_points = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    team = relationship("FantasyTeam", back_populates="roster_spots")
    player = relationship("FantasyPlayer", back_populates="roster_spots")

class FantasyMatchup(Base):
    """Weekly fantasy matchups"""
    __tablename__ = "fantasy_matchups"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    
    week = Column(Integer, nullable=False)
    matchup_id = Column(String(255))  # Platform-specific matchup ID
    
    team1_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    team2_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    team1_score = Column(Float, default=0)
    team2_score = Column(Float, default=0)
    
    is_complete = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague", back_populates="matchups")
    team1 = relationship("FantasyTeam", foreign_keys=[team1_id])
    team2 = relationship("FantasyTeam", foreign_keys=[team2_id])

class PlayerProjection(Base):
    """AI-generated player projections"""
    __tablename__ = "player_projections"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    week = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    
    # Projections
    projected_points = Column(Float, nullable=False)
    floor = Column(Float)  # Conservative projection
    ceiling = Column(Float)  # Optimistic projection
    
    # Matchup analysis
    opponent = Column(String(10))  # Opposing team
    vegas_implied_total = Column(Float)  # Team's implied total from betting lines
    game_script_score = Column(Float)  # Positive/negative game script
    
    # Advanced metrics
    target_share = Column(Float)  # For skill position players
    red_zone_looks = Column(Float)
    snap_percentage = Column(Float)
    
    # AI confidence and reasoning
    confidence = Column(Float, nullable=False)  # 0-100 confidence score
    reasoning = Column(Text)  # AI explanation
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("FantasyPlayer", back_populates="projections")

class FantasyRecommendation(Base):
    """YetAI fantasy recommendations"""
    __tablename__ = "fantasy_recommendations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    
    recommendation_type = Column(Enum(RecommendationType), nullable=False)
    week = Column(Integer, nullable=False)
    
    # Recommendation details
    title = Column(String(255), nullable=False)
    description = Column(Text)
    priority = Column(Integer, default=5)  # 1-10 priority scale
    
    # Player references
    primary_player_id = Column(Integer, ForeignKey("fantasy_players.id"))
    secondary_player_id = Column(Integer, ForeignKey("fantasy_players.id"))  # For trades
    
    # AI analysis
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text)
    expected_impact = Column(Float)  # Projected point impact
    
    # Status
    is_active = Column(Boolean, default=True)
    user_dismissed = Column(Boolean, default=False)
    user_acted = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    # Relationships
    user = relationship("User")
    league = relationship("FantasyLeague")
    primary_player = relationship("FantasyPlayer", foreign_keys=[primary_player_id])
    secondary_player = relationship("FantasyPlayer", foreign_keys=[secondary_player_id])

class FantasyTransaction(Base):
    """Track fantasy transactions for analysis"""
    __tablename__ = "fantasy_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    transaction_type = Column(Enum(TransactionType), nullable=False)
    week = Column(Integer)
    
    # Players involved
    added_player_id = Column(Integer, ForeignKey("fantasy_players.id"))
    dropped_player_id = Column(Integer, ForeignKey("fantasy_players.id"))
    
    # Transaction details
    waiver_priority = Column(Integer)
    fab_bid = Column(Integer)  # FAAB bid amount
    trade_details = Column(JSON)  # For complex trade data
    
    processed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    team = relationship("FantasyTeam")
    added_player = relationship("FantasyPlayer", foreign_keys=[added_player_id])
    dropped_player = relationship("FantasyPlayer", foreign_keys=[dropped_player_id])

class WaiverWireTarget(Base):
    """AI-identified waiver wire targets"""
    __tablename__ = "waiver_wire_targets"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    week = Column(Integer, nullable=False)
    
    # Opportunity metrics
    opportunity_score = Column(Float, nullable=False)  # 0-100 opportunity rating
    ownership_percentage = Column(Float)  # League ownership %
    trending_direction = Column(String(20))  # up, down, stable
    
    # Situation analysis
    situation_description = Column(Text)
    target_reason = Column(Text)  # Why this player is a target
    suggested_fab_percentage = Column(Float)  # FAAB % to bid
    
    # Projections
    rest_of_season_value = Column(Float)
    immediate_value = Column(Float)  # Next 2-3 weeks
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    player = relationship("FantasyPlayer")

class LeagueHistoricalData(Base):
    """Historical league data for competitor analysis"""
    __tablename__ = "league_historical_data"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    season = Column(Integer, nullable=False)
    
    # League metadata for historical season
    team_count = Column(Integer)
    waiver_type = Column(String(50))
    waiver_budget = Column(Integer)
    scoring_type = Column(String(50))
    
    # Raw data storage
    teams_data = Column(JSON)  # Team rosters, records, etc.
    transactions_data = Column(JSON)  # All transactions for season
    standings_data = Column(JSON)  # Final standings
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")

class CompetitorAnalysis(Base):
    """Analysis of competitor tendencies in leagues"""
    __tablename__ = "competitor_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    # Analysis period
    seasons_analyzed = Column(JSON)  # List of seasons included in analysis
    
    # Waiver wire tendencies
    avg_waiver_adds_per_season = Column(Float, default=0)
    preferred_positions = Column(JSON)  # Position preferences in adds
    waiver_aggressiveness_score = Column(Float)  # 0-100 aggressiveness rating
    
    # FAAB tendencies (if applicable)
    avg_faab_spent_per_season = Column(Float)
    high_faab_bid_threshold = Column(Float)  # Amount considered "high" for this manager
    faab_conservation_tendency = Column(String(20))  # conservative, moderate, aggressive
    
    # Position needs patterns
    common_position_needs = Column(JSON)  # Historical position needs by week
    panic_drop_tendency = Column(Float)  # Likelihood to make reactionary drops
    
    # Timing patterns
    waiver_claim_day_preferences = Column(JSON)  # When they typically make claims
    season_phase_activity = Column(JSON)  # Activity by early/mid/late season
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    team = relationship("FantasyTeam")

# Create indexes for better performance
from sqlalchemy import Index

# Add indexes for common queries
Index('idx_fantasy_user_platform', FantasyUser.user_id, FantasyUser.platform)
Index('idx_fantasy_league_sync', FantasyLeague.fantasy_user_id, FantasyLeague.is_synced)
Index('idx_roster_team_week', FantasyRosterSpot.team_id, FantasyRosterSpot.week)
Index('idx_projections_player_week', PlayerProjection.player_id, PlayerProjection.week, PlayerProjection.season)
Index('idx_recommendations_user_active', FantasyRecommendation.user_id, FantasyRecommendation.is_active)
Index('idx_waiver_targets_league_week', WaiverWireTarget.league_id, WaiverWireTarget.week)
Index('idx_historical_data_league_season', LeagueHistoricalData.league_id, LeagueHistoricalData.season)
Index('idx_competitor_analysis_league_team', CompetitorAnalysis.league_id, CompetitorAnalysis.team_id)